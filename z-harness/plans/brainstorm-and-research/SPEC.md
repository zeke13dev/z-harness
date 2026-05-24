# SPEC — brainstorm-and-research

> This SPEC was reconstructed after Phase 9 archive wiped the working copy. The acceptance criteria in `TASKS.md` are the binding contract; this file defines the cross-task contracts (artifact schemas, consultant return shapes, freshness algorithm) that those criteria reference.

## Overview

Two new opt-in slash commands precede `/z-plan` in the workflow chain:

- **`/z-brainstorm <topic>`** — cheap parallel idea generation across three vendor-diverse ideators (Claude + Codex + Gemini). Output: `BRAINSTORM.md`. Cost target: ≤200K tokens.
- **`/z-research <question>`** — heavier terrain mapping via parallel Explores + cross-LLM critique. Output: `RESEARCH.md`. Cost target: ≤2M tokens.

Both write into the same `z-harness/<slug>/` directory used by `/z-plan`. Either or both artifacts may exist when `/z-plan` runs; `/z-plan` Setup step 10 detects and incorporates them.

## Artifact contracts

### BRAINSTORM.md

YAML frontmatter (required fields):

```yaml
---
artifact: brainstorm
slug: <kebab>
generated_at: <UTC ISO 8601>
command: /z-brainstorm <args>
input_hash: <16 hex chars — see input_hash algorithm>
depends_on: [<RESEARCH.md if ingested>, ...]
ideators:
  - claude-sonnet
  - codex
  - gemini
  # failed ideator recorded as "<vendor>:failed"
status: complete | abandoned
chosen_framing: claude | codex | gemini | restart
---
```

Body sections (one block per ideator):

```markdown
## Framing: <ideator-name>

### Framing
<one paragraph>

### Core hypothesis
<one paragraph>

### Risks
<bulleted list>

### Plan implications
<bulleted list>

### What would change my mind
<bulleted list>
```

Followed by:

```markdown
## Anti-bias check
<section-by-section comparison; if orchestrator picks Claude over a peer, explicit justification required>

## Orchestrator recommendation
<one-line rationale; user is free to override>

## User choice
<persisted post-AskUserQuestion>
```

Missing/malformed sections are recorded as `<missing>` rather than omitted.

### RESEARCH.md

YAML frontmatter:

```yaml
---
artifact: research
slug: <kebab>
generated_at: <UTC ISO 8601>
command: /z-research <args>
input_hash: <16 hex>
depends_on: []
explore_calls: <N (0..3)>
status: complete | abandoned
---
```

Body sections (mandatory, in order):

```markdown
## Findings
<each finding cites file:line via the broadened regex; uncited findings are demoted to Open questions>

## Constraints discovered
<bulleted list>

## Open questions
<bulleted list>

## No-recommendation
This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.

## Cross-LLM review notes
<consultant feedback summary; filled vs unfilled gaps>
```

The `No-recommendation` section is invariant — non-deletable, regardless of orchestrator temptation. If the orchestrator finds itself drafting a recommendation, it logs a `research_temptation` event and proceeds without recommending.

## input_hash algorithm

```
input_hash = sha256(canonicalize(
    topic + "\n---\n" +
    doc_fetcher_synthesis_or_empty + "\n---\n" +
    explore_synthesis_or_empty + "\n---\n" +
    research_md_or_empty
)).hexdigest()[:16]
```

`canonicalize`: strip leading/trailing whitespace; collapse all internal runs of whitespace to single space. Deterministic across runs given identical inputs.

## Consultant mode extensions

### MODE: brainstorm (both codex-consultant and gemini-consultant)

- **Caller provides:** topic, scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary).
- **Consultant returns RAW** (not the standard `Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt` wrapper used by validation modes). The wrapper is for validation modes only. Brainstorm output is the five-section ideator block defined in BRAINSTORM.md body schema.
- **Section schema (must produce all five, mark `<missing>` only if the model truly cannot):**
  1. Framing
  2. Core hypothesis
  3. Risks
  4. Plan implications
  5. What would change my mind

### MODE: research-review (both consultants)

- **Caller provides:** research-note draft + original question + scaffolding.
- **Consultant returns RAW.** No standard wrapper.
- **Sections returned:**
  - Gaps (things the draft missed)
  - Errors (claims the draft made that appear wrong)
  - Missing constraints (constraints reviewer noticed that should be added)
- **Explicit prohibition:** must NOT recommend an approach. Research is terrain-mapping, not direction-picking. If the consultant tries, the reviewer prompt explicitly instructs them to omit it.

## /z-brainstorm phase contract

- **Setup:** slug derivation (auto from topic OR `--slug=X`); existing-slug-dir prompt (overwrite / append-to-new-run / abort); `Z_HARNESS_SLUG` export; RUN id; mkdir; version stamp; `brainstorm_run_start` event.
- **Phase 1 (Scaffolding):** doc-fetcher dispatch iff `docs/llm/INDEX.json` exists. Optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`. RESEARCH.md ingestion: full inline if ≤20 KB, extractive summary otherwise (summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
- **Phase 2 (Parallel dispatch):** ONE message with three `Agent()` calls in parallel:
  - Claude: `subagent_type="general-purpose", model="sonnet"`
  - Codex: `codex-consultant`, `MODE: brainstorm`
  - Gemini: `gemini-consultant`, `MODE: brainstorm`
  - **All three receive identical scaffolding payload** (no read-by-reference asymmetry; D5).
- **Phase 3 (Synthesis):** parse 3 returns; `<missing>` for malformed sections; write BRAINSTORM.md; anti-bias section-by-section comparison; orchestrator recommendation; `AskUserQuestion` with previews — option per framing + Restart + Abandon.
- **Phase 4 (Finalize):** persist user choice; `brainstorm_run_end` event; push-notify.

**Ideator failure policy:**
- 1/3 fail → proceed; anti-bias check explicitly two-way; `ideators` records failed member as `"<vendor>:failed"`.
- 2/3 fail → halt + `AskUserQuestion` retry/proceed-with-1/abandon (default: retry).
- 3/3 fail → hard halt, push-notify, `total_ideator_failure` event.

**Restart flow:** archive existing BRAINSTORM.md to `archive/<run>/BRAINSTORM.md.previous-<N>`; prompt for refined topic; start new RUN.

**Abandon flow:** set frontmatter `status: abandoned`; leave file in place; exit.

**Re-run on existing BRAINSTORM.md:** prompt overwrite / append (= move to `.previous-<N>`) / abort.

## /z-research phase contract

- **Setup:** mirrors /z-brainstorm; `research_run_start` event.
- **Phase 0 (Cost-confirmation gate):** `AskUserQuestion` proceed / reduce-to-1-Explore / abandon. Log user's pick.
- **Phase 1:** doc-fetcher dispatch iff INDEX.json exists.
- **Phase 2:** up to 3 parallel Explore subagents on distinct facets (or 1 if user reduced). Hard cap 3; no env override in v1.
- **Phase 3 (Draft):** write `archive/<run>/research-draft.md` with the mandatory sections.
- **Phase 4 (Critique):** bundled cross-LLM critique — `MODE: research-review` on both consultants, parallel dispatch.
- **Phase 5 (Revise):** revise draft; record consultant feedback in `Cross-LLM review notes`; note filled/unfilled gaps.
- **Phase 6 (Finalize):** write final RESEARCH.md; `research_run_end` event; push-notify with next-step.

**Invariants:**
- Findings without `file:line` citations are demoted to Open questions.
- `No-recommendation` section is non-deletable.
- If orchestrator drafts a recommendation, log `research_temptation` event and remove it.

**Known v1 limitation (documented in command file):** `Agent()` does not expose a per-call wall-clock timeout; subagents that hang block the run. User-facing escape: ctrl-c.

## /z-plan integration (T005)

### Setup step 10 (precontext detection)

- Check `z-harness/$Z_HARNESS_SLUG/` for `BRAINSTORM.md` and `RESEARCH.md`.
- **Freshness check (RESEARCH.md only):**
  - Citation regex: `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`
  - Extensionless allowlist scan: Makefile, Dockerfile.
  - Markdown link form `[label](path:line)` parsed by extracting inner path.
  - For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges use min-line mtime (any modification within range → stale).
  - Deleted-source detection → emit `precontext_source_deleted` event (higher severity than stale-mtime).
  - Parse failure → emit `precontext_freshness_check_failed`, continue (fail-open).
  - If any stale → `AskUserQuestion` warn the user before proceeding.
- **Conflict check:** if both BRAINSTORM and RESEARCH exist, surface any obvious contradictions to the user.
- **Unfinalized brainstorm** (`status: complete` missing or `chosen_framing` absent): recommend `/z-brainstorm` re-run before proceeding.

### Setup step 1 (slug collision handling)

Distinguish:
- **Precontext-only slug dir** (only BRAINSTORM.md and/or RESEARCH.md, no PLAN.md/SPEC.md/TASKS.md): treated as continuation, no prompt.
- **Finished-plan slug dir** (PLAN.md or TASKS.md exists): collision, prompt as today.

### Phase 0 (Premise check)

Prose addition: "If BRAINSTORM.md or RESEARCH.md were detected in Setup step 10, **inject their content here** as input to the premise check."

### Phase 1 (Exploration) — boundary tightening

"If RESEARCH.md is non-stale AND covers ≥1 distinct facet of the task, doc-fetcher and Explore become optional."

More precisely:
- Skip doc-fetcher iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
- Skip Explore iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.

### Phase 6 (SPEC.md template)

Add `## Planning Inputs` section listing which precontext artifacts contributed (paths + `generated_at`), or "none — fresh /z-plan run."

## Telemetry alignment

Use the existing `log-event.sh` shape. Standard fields: `prompt_chars`, `response_chars`, `wall_ms`. `tokens_spent` is NOT in per-event payload (out of scope until `log-event.sh` is extended; `/z-stats` can compute approximate spend from chars × ratio).

New event kinds introduced by these commands:
- `brainstorm_run_start`, `brainstorm_run_end`
- `research_run_start`, `research_run_end`
- `ideator_failed` (fields: vendor, reason)
- `total_ideator_failure`
- `research_temptation`
- `precontext_source_deleted`
- `precontext_freshness_check_failed`
- `doc_drift_acknowledged` (already exists)

## Known v1 limitations

- No per-Explore wall-clock timeout (Agent() limitation; subagents that hang block the run; user uses ctrl-c).
- No doc-fetcher caching across precontext + plan runs (marked as v2 candidate; cheap enough today).
- No pluggable ideator model list (default `[claude-sonnet, codex, gemini]`; future v2).
