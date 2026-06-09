# BRAINSTORM: Specialized Doc Updater Agent

> Mode: interactive premise refinement → converged design
> Date: 2026-06-09
> Status: converged, ready for `/z-plan`

---

## 1. The Pain & Reframing

### The pain

Maintaining docs by running explicit shell commands (like `/z-maintain-docs`)
is broken in three compounding ways:

1. **Separate step.** You finish a pipeline, context evaporates, then you
   remember "oh right, docs" and fire a separate invocation.
2. **Context-starved.** `/z-maintain-docs` wakes up cold, reads source files
   from disk, and mechanically updates structural docs. It has zero knowledge
   of WHY changes were made — what decisions were contested, what approaches
   were tried and failed, what the implementer discovered mid-stream.
3. **Expensive for what it does.** A full Pro invocation to compare timestamps,
   grep for changed function names, and regenerate tables. The warm pipeline
   context was free; the cold doc run pays full freight.

### The reframing

Stop making doc maintenance a separate step. Embed it in the pipeline where
context is warm. This produces two tiers:

- **Tier 1** — Per-task, cheap, stateless, mechanical. The **diff IS the spec.**
  No LLM reasoning — just pattern-match and update machine-truth fields.
- **Tier 2** — End-of-pipeline, Pro-tier, narrative. Captures context while
  warm, defers the human conversation until the user is ready. Produces ADRs,
  design rationale, migration guides, tried-and-failed sections.

Both tiers run **automatically** — invisible capture, zero manual invocation.
The only human interaction is a lightweight gap-fill conversation at Tier 2
time (10-30 seconds).

---

## 2. Overview: Two-Tier Architecture

```
/z-plan
  ├─ Phase N: consultant critique → log dispositions to tier2-context.json
  │
/z-implement-all
  ├─ T001: implementer → reviewer
  │   └─ Tier 1: diff-only surgical update, stage to temp
  ├─ T002: implementer → reviewer
  │   └─ Tier 1: diff-only surgical update, stage to temp
  ├─ ... T020
  └─ Reconciliation: deduplicate staged updates, apply once
      ├─ Regenerate INDEX.json last_updated, source_files
      └─ Regenerate MEMORIES-FLAT.md
      │
/z-review-all
  ├─ Phase N: cross-LLM review → log review_patterns to tier2-context.json
  ├─ Context capture: serialize tier2-context.json from accumulated fields
  └─ Push: "Pipeline complete. /z-doc-rationale ready."
      │
/z-doc-rationale (user runs when ready)
  ├─ Read tier2-context.json (3K tokens)
  ├─ Spawn Pro-tier subagent → produce draft ADRs, rationale, migration guides
  ├─ Gap-fill conversation (10-30 sec, human fills what pipeline couldn't capture)
  └─ Write finals to archive + cross-link into concept docs
```

| | Tier 1 | Tier 2 |
|---|---|---|
| **Trigger** | Per-task, auto | End-of-pipeline, auto-recommended |
| **Model** | Flash | Pro |
| **Cost** | ~$0.02/plan (subagent tokens) | ~$0.04-0.08/significant plan |
| **Input** | Single-task diff + current doc | `tier2-context.json` (3K tokens) |
| **Output** | Machine-truth doc fields | ADRs, rationale, tried-and-failed, migration guides |
| **Writes to** | `docs/human/*.md`, `docs/llm/*.json` | `z-harness/plans/<slug>/tier2/` + cross-links |
| **Human interaction** | None (invisible) | One gap-fill conversation at user's convenience |

---

## 3. Tier 1: Per-Task Mechanical Doc Sync

### 3.1 Trigger & Flow

After each task's implementer+reviewer cycle passes, the orchestrator runs Tier 1
on the task's diff:

```
1. git diff HEAD~1 --name-only
   → determine which files changed

2. Reverse-lookup files → concepts
   Read INDEX.json, grep source_files
   → ["feed-router", "market-data"]

3. For each concept with changed source files:
   a. Read current docs/human/<concept>.md and docs/llm/<concept>.json
   b. Parse diff for changed signatures, exports, config keys
   c. Apply surgical updates to machine-truth fields
   d. Stage updated docs to tier1-staged/<concept>/

4. Log: "T003: feed-router machine-truth updated"
```

After all tasks complete, reconciliation applies staged updates.

### 3.2 Core Principle: The Diff IS the Spec

No LLM reasoning. No source-file reading beyond what's needed to find the
target in the doc. The diff explicitly shows additions (`+`) and removals
(`-`). Tier 1 pattern-matches those against machine-truth doc fields and
applies surgical updates.

Flash-tier subagent model is used — cheap, stateless, context-scoped to one
task's diff. The only intelligence needed is matching diff patterns to doc
patterns. No generation, no prose writing, no understanding.

### 3.3 Scope: Per-Artifact Boundaries

| Artifact | Tier 1 Updates | Tier 1 Skips | Mechanism |
|---|---|---|---|
| **Inline docstrings** | Patch signature reference line in docstring. Only when: (a) signature changed in diff, AND (b) docstring was NOT changed in diff. | Docstring body. Full docstring regeneration. | One-line surgical replace in source file. |
| **Concept doc entry_points** | Add/remove/update entries matching `+`/`-` lines in diff. Update line numbers for changed functions. | Reorderings. Visibility semantics (`pub` → `pub(crate)`). Complete section regeneration. | Pattern-match diff hunks → entry_points array in LLM JSON. |
| **Concept doc signatures** | Update function signatures in human-tier and LLM-tier when diff shows change. | Dependency graph implications. Prose descriptions of what the function does. | Find-and-replace signature string. |
| **Config tables** | Add/remove/update rows matching config key changes in diff. Update type/ default/value columns. | Description prose column. | Pattern-match config key → table row. |
| **README API references** | Detect stale symbol references. Surface as **warning only** — never auto-update. | All README content. | Grep for changed symbols in README. Emit drift warning. |
| **INDEX.json** | Update `last_updated` for touched concepts. Add/remove `source_files` entries matching `+`/`-` paths. | `depends_on`, `consumed_by`, `summary`, `confidence`. | Timestamp + surgical array edit. |
| **MEMORIES-FLAT.md** | Full regeneration from all concept JSONs during reconciliation. | N/A — always deterministic from concept JSONs. | Run `regenerate-memories-flat.py` once. |
| **Export lists** | Add/remove entries when diff shows `+ pub` / `- pub` lines. | Export list order. Visibility-only changes. | Pattern-match export line → entry in doc section. |

### 3.4 Delimiter Markers

Machine-truth sections in human-tier docs are delimited:

```markdown
## Key entry points

<!-- AUTO-START: entry-points -->
- `src/feed/router.rs:42` — `dispatch(data, pool)` — Dispatch feed data
- `src/feed/config.rs:15` — `FeedConfig` — Feed configuration
<!-- AUTO-END: entry-points -->

## Overview

(Prose — never touched by Tier 1)
```

Tier 1 only writes between `AUTO-START` / `AUTO-END` markers. Everything
outside is human-owned and never mechanically touched.

Sections that get markers:
- `entry-points` — function signatures, file paths, line numbers
- `config-table` — config key rows (key, type, default, values columns only)
- `exports` — public export lists
- `design-decisions` — cross-links to ADRs (Tier 2 writes these, not Tier 1)
- `memories` — memory entries from LLM JSON (regenerated, not manually edited)

### 3.5 Staging & Reconciliation

**Per-task staging:** Tier 1 writes updated docs to
`z-harness/plans/<slug>/tier1-staged/<concept>/human.md` and
`<concept>/llm.json`. Never writes to `docs/` directly during the task loop.

**Reconciliation (after all tasks):**

```
For each concept with staged updates:
  - Read tier1-staged/<concept>/human.md
  - Read current docs/human/<concept>.md
  - Merge: replace AUTO-START...AUTO-END sections with staged versions
  - Preserve everything outside delimiters
  - Same merge for docs/llm/<concept>.json
    (update entry_points, source_file, last_updated;
     preserve depends_on, consumed_by, summary, confidence, memories)
  - Write merged version to docs/

Update INDEX.json:
  - For each touched concept: update last_updated, source_files
  - Preserve all other fields

Regenerate MEMORIES-FLAT.md:
  - Run regenerate-memories-flat.py from ALL concept JSONs
  - Covers memory changes from /z-suggest-memory between phases
```

Latest-wins for overlapping staged updates (same concept touched by multiple
tasks — the last task's regeneration is applied).

### 3.6 Cost

Two models possible:

**A. Subagent per task (Flash):** Each task spawns a Flash subagent to read
the diff and apply surgical updates. ~$0.001/task × 20 tasks = ~$0.02/plan.
Provides richer pattern-matching (Flash can handle edge cases like renamed
symbols with changed signatures in the same diff).

**B. Script-only ($0):** A Python script does the surgical updates. No
subagent. Faster but handles fewer edge cases (complex renames, multi-hunk
diffs spanning the same function).

Decision deferred to `/z-plan` — the architecture supports either. The
Flash subagent model is the default because "the diff IS the spec" but
real-world diffs have enough edge cases that a small LLM handles them
better than regex.

---

## 4. Tier 2: End-of-Pipeline Narrative Docs

### 4.1 Trigger & Significance Gate

Tier 2 fires after `/z-review-all` completes (when full pipeline context
is available). A **three-signal OR gate** determines whether Tier 2 is
recommended:

| Signal | Detection | If fires |
|---|---|---|
| Cross-LLM consult | `consultant_findings[]` non-empty | At least one consultant review happened |
| Breaking changes | `breaking_changes[]` non-empty | Config key renamed, public API changed |
| Plan deviations | `deviations[]` non-empty | Implementer changed what plan specified |

**Any one signal → Tier 2 recommended:**

```
Pipeline complete. 2 breaking changes, 3 plan deviations.
Tier 2 context captured. Run /z-doc-rationale to produce design docs.
```

**No signals → Tier 2 skipped automatically:**

```
Pipeline complete. No significant design decisions.
Tier 2 skipped. Machine-truth docs updated (3 concepts).
```

**False positives are cheap** ($0.04-0.08, 10 seconds human time). **False
negatives are expensive** (permanent institutional memory loss). The
asymmetry favors firing.

### 4.2 Context Accumulation: Phase by Phase

The orchestrator writes to `tier2-context.json` **incrementally** during the
pipeline, not at the end. No single-pass compaction from 100K+ tokens.

**`/z-plan` phase:**

The orchestrator reads consultant responses, categorizes each finding as
accepted / rejected / deferred, and appends to the context file:

```jsonc
// APPENDED during /z-plan
{
  "spec_summary": "Refactor feed dispatch to use thread pool...",
  "plan_summary": "3 workstreams: feed-router, market-data, order-book",
  "decisions": [
    {
      "id": "concurrency-model",
      "phase": "planning",
      "chosen": "thread pool",
      "rejected": ["async dispatch", "single-threaded"],
      "rationale": "SPEC deferred thread pool investigation to implementation",
      "consultant_consensus": "mixed — Codex preferred async, Gemini flagged deadlock"
    }
  ],
  "consultant_findings": [
    {
      "finding": "async dispatch deadlock risk",
      "source": "consultant-secondary",
      "severity": "MEDIUM",
      "disposition": "acknowledged but deferred",
      "reason": "SPEC says investigate during implementation"
    }
  ]
}
```

**`/z-implement-all` phase (per task):**

After each implementer returns with RATIONALE / TRIED / DEVIATIONS fields,
and the reviewer validates DEVIATIONS, the orchestrator appends:

```jsonc
// APPENDED per task during /z-implement-all
{
  "tried_and_failed": [
    {
      "task": "T003",
      "concept": "feed-router",
      "attempts": [
        {
          "approach": "tokio::spawn + Mutex<ConnectionPool>",
          "failure": "Deadlocked — Mutex not Send across await points"
        },
        {
          "approach": "Arc<Mutex<ConnectionPool>>",
          "failure": "Lock contention, 80% throughput drop at 8+ concurrent feeds"
        }
      ],
      "chose": "rayon::scope thread pool",
      "reviewer_validated": false
    }
  ],
  "deviations": [
    {
      "task": "T003",
      "deviation": "Added thread_pool.rs (not in PLAN)",
      "reason": "Rayon integration required dedicated module",
      "reviewer_validated": true,
      "reviewer_note": "Confirmed — file added, necessary for thread pool"
    },
    {
      "task": "T003",
      "deviation": "Removed tokio dependency from feed-router",
      "reason": "Async runtime no longer needed",
      "reviewer_validated": true
    }
  ],
  "breaking_changes": [
    {
      "api": "feed::dispatch()",
      "old": "fn dispatch(data: &[u8])",
      "new": "fn dispatch(data: &[u8], pool: &ThreadPool)",
      "consumers": 15,
      "breaking": true
    }
  ]
}
```

**`/z-review-all` phase:**

After cross-LLM review, the orchestrator appends aggregate patterns:

```jsonc
// APPENDED during /z-review-all
{
  "review_patterns": [
    {
      "pattern": "Thread pool adopted independently across 3 subsystems",
      "source": "consultant-primary (review mode)",
      "finding": "Pattern emerged in T003, T009, T015 independently. Consistent.",
      "recommendation": "Consider extracting shared thread pool config (future work)"
    }
  ],
  "gaps": [
    {
      "field": "human_overrides",
      "status": "filled — human override for concurrency-model captured at decision time"
    }
  ]
}
```

**Final pass:**

The orchestrator validates the accumulated context for completeness, detects
gaps, and writes the finalized `tier2-context.json`. Total size: ~3-5K tokens.

### 4.3 tier2-context.json Schema

```jsonc
{
  "plan": "dispatch-refactor",
  "generated_at": "2026-06-09T14:30:00Z",
  "finalized": true,

  "spec_summary": "string — 1-3 sentence summary from SPEC.md",
  "plan_summary": "string — workstream overview from PLAN.md",

  "decisions": [
    {
      "id": "string — unique per decision within this plan",
      "phase": "planning | implementation | review",
      "chosen": "string — what we chose",
      "rejected": ["string — alternatives considered and rejected"],
      "rationale": "string — why, from consultant critique or implementer discovery",
      "consultant_consensus": "agree | disagree | mixed — cross-LLM alignment",
      "human_override": true,
      "human_reason": "string — if human overrode the decision",
      "adr_worthy": true
    }
  ],

  "consultant_findings": [
    {
      "finding": "string — consultant summary",
      "source": "consultant-primary | consultant-secondary",
      "severity": "CRITICAL | HIGH | MAJOR | MEDIUM | LOW",
      "disposition": "accepted | rejected | deferred | modified",
      "reason": "string — why this disposition"
    }
  ],

  "tried_and_failed": [
    {
      "task": "string — e.g. T003",
      "concept": "string — concept slug",
      "attempts": [
        {
          "approach": "string — what was tried",
          "failure": "string — why it failed"
        }
      ],
      "chose": "string — what worked instead",
      "reviewer_validated": true
    }
  ],

  "deviations": [
    {
      "task": "string",
      "deviation": "string — what differed from plan",
      "reason": "string — why",
      "reviewer_validated": true,
      "reviewer_note": "string"
    }
  ],

  "breaking_changes": [
    {
      "api": "string — function, config key, or export path",
      "old": "string — before",
      "new": "string — after",
      "consumers": 0,
      "breaking": true
    }
  ],

  "review_patterns": [
    {
      "pattern": "string — aggregate pattern observed across tasks",
      "source": "string — which reviewer flagged it",
      "finding": "string — what was found",
      "recommendation": "string"
    }
  ],

  "human_overrides": [
    {
      "phase": "planning | implementation | review",
      "decision_id": "string — references decisions[].id",
      "override": "string — what was overridden",
      "reason": "string — captured at decision time",
      "overrides_consultant": true,
      "consultant_affected": "string"
    }
  ],

  "gaps": [
    {
      "field": "string — path in context, e.g. human_overrides[0].reason",
      "status": "filled | missing",
      "note": "string — if missing, what's needed"
    }
  ]
}
```

### 4.4 Gap-Fill Conversation Model

When the user runs `/z-doc-rationale`:

1. Read `tier2-context.json` (3-5K tokens)
2. Spawn Pro-tier subagent → produce draft ADRs, rationale, migration guides
3. Detect gaps from `gaps[]` field
4. Present ONLY gaps, not full document review:

```
/z-doc-rationale
─────────────────
2 ADRs, 1 rationale doc ready. 1 gap to fill.

ADR-006 (concurrency-model):
  Why did you override the consultant's recommendation?
  Consultant recommended async dispatch.
  You chose thread pool instead.
  Reason not captured at decision time.

  Type reason or press Enter to skip: █
─────────────────
```

If the human types a reason, it's filled. If Enter is pressed without input,
the gap stays flagged and the ADR includes:

> Human override reason not captured at decision time.

**The document ships with honest gaps, not fabrications.**

**Human override capture at decision time** eliminates most gaps before the
conversation. When the human overrides a decision during any pipeline phase,
the orchestrator asks "why?" immediately while the reasoning is fresh. The
end-of-pipeline gap-fill conversation should find zero gaps for well-captured
runs.

### 4.5 Outputs & Discoverability

Tier 2 produces files in `z-harness/plans/<slug>/tier2/`:

| Output | File | From context field |
|---|---|---|
| ADRs | `ADR-NNN-<title>.md` | `decisions[]` where `adr_worthy: true` |
| Design rationale | `rationale.md` | `spec_summary` + `decisions[]` + `review_patterns[]` |
| Tried and failed | Section in `rationale.md` | `tried_and_failed[]` |
| Tradeoff explanations | Section in `rationale.md` | `decisions[]` + `review_patterns[]` |
| Migration guide | `migration-guide.md` | `breaking_changes[]` + `deviations[]` |

**Discoverability (MVP):** Tier 2 appends a `design-decisions` section to
concept docs with links to ADRs:

```markdown
<!-- AUTO-START: design-decisions -->
## Design decisions

- [ADR-006: Thread pool vs. async dispatch](../../z-harness/plans/dispatch-refactor/tier2/ADR-006-thread-pool.md)
<!-- AUTO-END: design-decisions -->
```

`doc-fetcher` reads concept docs and returns these links naturally when
querying the concept.

**Discoverability (v2 — deferred):** INDEX.json gets an `adr_index` section
with keyword-searchable ADR entries. `doc-fetcher` grows `kind: rationale`
query mode. See Open Questions.

**Confidence caveat on tried-and-failed entries:**

```
### What we tried and failed
> ⚠ Auto-generated from implementer self-reports. May contain inferred
> or incomplete information. Reviewer validation: partial.

- **async + tokio::spawn** — Deadlocked under concurrent load.
  _Source: T003 implementer TRIED. Reviewer did not validate._
- **Arc<Mutex<ConnectionPool>>** — Lock contention, 80% throughput drop.
  _Source: T003 implementer TRIED. Reviewer did not validate._
```

### 4.6 Cost

| Component | Tokens | Cost (Pro) |
|---|---|---|
| Read `tier2-context.json` | ~3K input | $0.006 |
| System prompt (skill definition) | ~2K input | $0.004 |
| Generate outputs (drafts) | ~4K output | $0.032 |
| Human conversation (2 turns) | ~2K total | $0.010 |
| **Total** | **~11K** | **~$0.05** |

For a plan with 1 ADR and no migration guide: ~$0.02-0.04. For a plan
that doesn't meet the significance gate: $0 (skipped).

Tier 2 is ~3-5% of total pipeline cost. The cold alternative — running
`/z-maintain-docs` on a fresh Pro invocation that reads everything from
disk — costs roughly the same and produces structural updates only, not
narrative docs.

---

## 5. Implementer Return Contract

To populate `tier2-context.json`, implementer subagents return three new
fields:

```
TASK: T003
STATUS: done
CHANGES: [src/feed/router.rs, src/feed/thread_pool.rs]

RATIONALE: "SPEC called for async dispatch. Deadlocked under concurrent
           load because Mutex<ConnectionPool> isn't Send across await
           points. Switched to rayon::scope thread pool — avoids the
           Send constraint entirely. Reviewer confirmed."

TRIED: [
  "tokio::spawn + Mutex — deadlocked (Send constraint)",
  "Arc<Mutex<ConnectionPool>> — solved Send but lock contention
   dropped throughput 80% under 8+ concurrent feeds"
]

DEVIATIONS: [
  "Added thread_pool.rs — not in original PLAN; necessary for rayon integration",
  "Removed tokio dependency from feed-router — async runtime no longer needed"
]
```

| Field | Required? | Validated by | Used by Tier 2 for |
|---|---|---|---|
| `RATIONALE` | Yes | Reviewer (plausibility check) | Design rationale, why-decisions |
| `TRIED` | Optional | Reviewer (code consistency only) | Tried-and-failed sections |
| `DEVIATIONS` | Optional | Reviewer (validates against diff) | Migration guides, plan deviation narrative |

**Reviewer extension:** The reviewer's brief is extended to validate
DEVIATIONS against the diff and check RATIONALE plausibility. Reviewer
cannot validate TRIED entries (the dead code was never committed), but
can flag gross inconsistencies ("TRIED says thread pool but code still
uses tokio::spawn").

---

## 6. Human Override Capture at Decision Time

When the human overrides a pipeline decision, the orchestrator captures
the reason **immediately** while reasoning is fresh:

```
Pipeline (during /z-plan):
  "Consultant recommends async dispatch for feed-router."
  "Continue with async? [Y/n]"

Human: "No, use thread pool."
Orchestrator: "Why thread pool over async? (press Enter to skip)"
Human: "GCP migration Q3 — threads are safer for now."
Orchestrator: "Logged."

→ Writes to tier2-context.json.human_overrides[] immediately
```

The end-of-pipeline gap-fill conversation finds this reason already captured.
Zero gaps for well-captured runs. The "why?" prompt adds one brief interaction
during the pipeline — accepted as reasonable friction since reasoning is fresh.

---

## 7. Six Tensions & Resolutions

### 7.1 Implementer Unreliability — RESOLVED

**Tension:** TRIED field depends on metacognitive honesty. Reviewer cannot
validate it. Implementers might fabricate or omit.

**Resolution:** Keep the field. Lower the authority. Tier 2 output includes
per-entry source attribution and a caveat banner. Reviewer partially validates
via code consistency check (gross fabrications are caught; subtle ones are not).
The documents are useful, not authoritative.

### 7.2 Orchestrator Context Saturation — RESOLVED

**Tension:** Serializing `tier2-context.json` is the last operation in a
saturated 100K+ token context window.

**Resolution:** Incremental compaction across pipeline phases. The orchestrator
appends to `tier2-context.json` as decisions happen, not at the end. No single
context dump. The final pass (gap detection) reads back the compacted 3K JSON,
not the raw transcripts.

### 7.3 Machine-Truth Boundary — RESOLVED PER ARTIFACT

**Tension:** Some "mechanical" changes require semantic understanding.
Visibility changes (`pub` → `pub(crate)`), reorderings, prose references.

**Resolution:** Explicit per-artifact boundaries (see Section 3.3). Tier 1
touches only what the diff explicitly shows. Visibility changes, reorderings,
and prose references are out of scope. They drift until `/z-maintain-docs`
catches them. For v2: language-aware parsers as plugins.

### 7.4 Discoverability — RESOLVED

**Tension:** Tier 2 writes to plan archive. `doc-fetcher` can't find ADRs.

**Resolution:** MVP: Tier 2 appends `design-decisions` section to concept docs
with direct links to ADRs and rationale. `doc-fetcher` finds them naturally
when reading concept docs. v2: `adr_index` in INDEX.json + `kind: rationale`
query mode in doc-fetcher.

### 7.5 Conversation Weight — RESOLVED

**Tension:** Tier 2 requires human interaction. Is this the same friction
as the explicit shell commands we're eliminating?

**Resolution:** Not the same. Gap-fill is targeted (only missing reasons, not
full document review), lightweight (10-30 seconds), and deferred (user runs
when ready). Human override capture at decision time eliminates most gaps
before the conversation. Documents ship with honest gaps, not fabrications,
if the human skips.

### 7.6 Significance Threshold — RESOLVED

**Tension:** Not every plan needs Tier 2. A 3-line fix doesn't need an ADR.

**Resolution:** Three-signal OR gate (cross-LLM consult, breaking changes,
plan deviations). Any one fires → Tier 2 recommended. None fire → skipped
automatically. False positives are cheap ($0.04, 10 seconds). False negatives
are expensive (lost institutional memory). Err on firing.

---

## 8. Relationship to Existing Commands

| Command | Role after this design |
|---|---|
| **`/z-maintain-docs`** | Periodic deep clean (quarterly). Catches: prose drift, stale memories, tag collisions, visibility semantics Tier 1 missed. Still needed — not replaced. |
| **`/z-init-docs`** | Bootstrap two-tier docs. Add delimiter markers to existing concept docs. Unchanged. |
| **`/z-suggest-memory`** | Author/edit memory entries. Unchanged — Tier 1 and Tier 2 never touch memories. |
| **`/z-improve`** | Retrospective harness improvement. Complementary to Tier 2 — different output (harness fixes vs. design docs), different consumer. |

**`/z-maintain-docs` is NOT replaced. It is the fallback for everything Tier 1
and Tier 2 don't cover.** Tier 1 covers machine-truth freshness. Tier 2 covers
design narrative. `/z-maintain-docs` covers everything else: stale memories,
semantic prose drift, tag collisions, visibility semantics, full concept
refresh.

---

## 9. Open Questions for v2

### 9.1 doc-fetcher kind:rationale

INDEX.json gets `adr_index` with keyword-searchable ADR entries. `doc-fetcher`
grows `kind: rationale` query mode to search ADRs by title/keyword. Future
agents asking "why does dispatch use threads?" find ADR-006 directly.

### 9.2 Language-Aware Parsers

Tier 1 currently skips visibility changes (`pub` → `pub(crate)`) because they
require language-specific parsing. v2: optional per-language parser plugins
(Rust, Python, TypeScript) that extract visibility, docstrings, exports with
full semantic understanding. Incrementally closes the machine-truth boundary.

### 9.3 ADR Numbering

ADR numbers are sequential across the whole project. Tier 2 reads the
`docs/adr/` directory, finds the max number, allocates N+1. Concurrent
plans could collide — the active-plan-registry already handles this for
plan artifacts; extension to ADR numbering is a v2 concern.

### 9.4 Cross-Workstream Tradeoff Synthesis

Tier 2 per-run captures within-plan tradeoffs. Cross-plan synthesis (patterns
that emerge across multiple independent plans) requires a separate mechanism —
a periodic synthesis run or human-driven retrospective. Out of scope for MVP.

### 9.5 Tier 1 Subagent vs. Script

The architecture supports either a Flash subagent or a Python script for Tier 1
surgical updates. The Flash subagent handles edge cases better (complex renames,
multi-hunk diffs). The script is faster and $0. Decision deferred to
implementation — start with Flash, optimize to script if cost/performance data
supports it.

---

## 10. Cost Model Summary

| Component | Frequency | Cost | Total / plan |
|---|---|---|---|
| Tier 1 subagent (Flash, per task) | 20 tasks | ~$0.001/task | ~$0.02 |
| Tier 1 reconciliation (script) | Once | $0 | $0 |
| Tier 2 context capture | Incremental | $0 (warm context) | $0 |
| Tier 2 subagent (Pro) | Once, if gated | ~$0.05 | $0-0.05 |
| Tier 2 human conversation | Once, if gated | 10-30 sec | 10-30 sec |
| **Total (significant plan)** | | | **~$0.07 + 10-30 sec** |
| **Total (non-significant plan)** | | | **~$0.02, no human time** |

Compared to the cold alternative (one `/z-maintain-docs` invocation: ~$0.03-0.05,
provides structural refresh only, no narrative docs), the Tier 1+2 model is
cost-neutral for structural docs and adds narrative documentation for ~$0.02-0.05
marginal cost. The primary improvement is quality (warm context, design decisions
captured) and eliminating the "remember to run" friction.
