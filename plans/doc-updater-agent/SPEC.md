# SPEC: doc-updater-agent — Two-Tier Automatic Doc Maintenance

> Generated: 2026-06-09
> Slug: doc-updater-agent
> Status: plan

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | plans/doc-updater-agent/BRAINSTORM.md | 2026-06-09 |

---

## Overview

Embed doc maintenance in the z-harness pipeline where context is warm, split into two tiers:
- **Tier 1:** Per-task mechanical doc sync — Flash subagent applies diff-only surgical updates to machine-truth fields in delimited doc sections. Staged per task, reconciled at end of z-implement-all.
- **Tier 2:** End-of-pipeline narrative docs — Pro subagent reads incrementally accumulated `tier2-context.json` (3-5K tokens) and produces ADRs, design rationale, tradeoff explanations, migration guides. Significance-gated (three-signal OR: cross-LLM consult, breaking changes, plan deviations).

`/z-maintain-docs` is NOT replaced — remains as quarterly deep-clean fallback.

---

## New Files

### 1. `agents/tier1-doc-updater.md` — Tier 1 Mechanical Doc Sync Subagent

**Model:** Flash (pinned)
**Invoked by:** z-implement-all orchestrator, per task after reviewer passes
**Inputs:** Task diff (`git diff HEAD~1`), INDEX.json (for file→concept reverse lookup), current docs/human/<concept>.md and docs/llm/<concept>.json for each affected concept
**Behavior:**
1. Read INDEX.json; reverse-lookup changed files → concepts
2. For each concept: read current human doc and LLM JSON
3. Parse diff for changed signatures, exports, config keys, entry points
4. Apply surgical updates to machine-truth fields ONLY between `<!-- AUTO-START: ... -->` / `<!-- AUTO-END: ... -->` markers
5. Write updated docs to `$Z_HARNESS_PLAN_DIR/tier1-staged/<concept>/human.md` and `llm.json`
6. Never write to `docs/` directly; never touch prose outside delimiters; never touch memories[]

**Machine-truth fields updated:**
| Diff signal | Doc field updated | Markers |
|---|---|---|
| `+ fn new_func(` | `entry-points` section | `AUTO-START: entry-points` |
| `- fn old_func(` | `entry-points` section (remove) | `AUTO-START: entry-points` |
| Changed signature on existing fn | `entry-points` line for that fn | `AUTO-START: entry-points` |
| `+ pub fn`, `+ pub struct` | `exports` section | `AUTO-START: exports` |
| `- pub fn`, `- pub struct` | `exports` section (remove) | `AUTO-START: exports` |
| Config key `+`/`-` or type change | `config-table` rows | `AUTO-START: config-table` |
| New/removed source file | `source_file` in LLM JSON | N/A (JSON field) |

**Skips (out of scope):** visibility-only changes (`pub`→`pub(crate)`), reorderings, prose descriptions, dependency graph implications, docstring bodies, README content (drift warning only)

**Return contract:**
```
STATUS: ok | partial | nothing_to_update
CONCEPTS_TOUCHED:
  - <slug>: <summary of changes>
DRIFT_WARNINGS:
  - <file:line>: <stale symbol reference>
```

**Invariants:**
- Reads diff only (not full source files beyond what's needed)
- Writes to staging directory only, never `docs/`
- Never modifies prose outside AUTO-START/AUTO-END markers
- Never touches `memories[]`
- Idempotent: re-running on same diff produces identical output

---

### 2. `commands/z-doc-rationale.md` — Tier 2 Narrative Doc Command

**Model:** Pro (subagent)
**Invoked by:** User runs `/z-doc-rationale` when prompted after pipeline
**Inputs:** `$Z_HARNESS_PLAN_DIR/tier2-context.json` (3-5K tokens)
**Behavior:**
1. Read tier2-context.json
2. If `finalized: false` → abort with "Tier 2 context not yet finalized. Complete the pipeline first."
3. Spawn Pro subagent to produce drafts:
   - ADRs from `decisions[]` where `adr_worthy: true`
   - `rationale.md` from `spec_summary` + `decisions[]` + `review_patterns[]`
   - `migration-guide.md` from `breaking_changes[]` + `deviations[]`
4. Detect gaps from `gaps[]` field
5. Present ONLY gaps to user (not full document review):
   ```
   /z-doc-rationale
   2 ADRs, 1 rationale doc ready. 1 gap to fill.
   ADR-006 (concurrency-model):
     Why did you override the consultant's recommendation?
     Type reason or press Enter to skip: █
   ```
6. User's input fills the gap; Enter without input = gap stays flagged
7. Write final documents to `$Z_HARNESS_PLAN_DIR/tier2/`

**Output files:**
| Output | File | Source field |
|---|---|---|
| Architecture Decision Records | `ADR-NNN-<title>.md` | `decisions[]` where `adr_worthy: true` |
| Design rationale | `rationale.md` | `spec_summary` + `decisions[]` + `review_patterns[]` |
| Migration guide | `migration-guide.md` | `breaking_changes[]` + `deviations[]` |

**Confidence caveat on tried-and-failed:**
```
> ⚠ Auto-generated from implementer self-reports. May contain inferred
> or incomplete information. Reviewer validation: partial.
```
Each TRIED entry includes source attribution (`Source: T003 implementer TRIED. Reviewer did not validate.`)

**Discoverability:** Appends `<!-- AUTO-START: design-decisions -->` section with links to ADRs in each affected concept's human doc.

**Invariants:**
- Never fabricates gap content — documents ship with honest gaps
- Preserves human_overrides[] with captured-at-decision-time reasons
- Memoizes: if tier2-context.json hash hasn't changed since last run, skip regeneration

---

### 3. `scripts/append-tier2-context.py` — Incremental Context Accumulation

**Usage:**
```bash
python3 scripts/append-tier2-context.py \
  --phase plan|implement|review \
  --field decisions|consultant_findings|tried_and_failed|deviations|breaking_changes|review_patterns|gaps|human_overrides \
  --json '<JSON payload matching schema field>'
```

**Behavior:**
1. Read `$Z_HARNESS_PLAN_DIR/tier2-context.json` (or init empty if absent)
2. Append payload to the named array field
3. Write back atomically (tmp file + os.replace)
4. Validate JSON schema on every write — reject invalid payloads

**Exit codes:** 0=success, 1=schema validation failure, 2=write error

**Schema validation rules:**
- `decisions[]`: must have `id`, `phase`, `chosen`, `rationale`
- `consultant_findings[]`: must have `finding`, `source`, `severity`, `disposition`
- `tried_and_failed[]`: must have `task`, `concept`, `attempts[]`, `chose`
- `deviations[]`: must have `task`, `deviation`, `reason`
- `breaking_changes[]`: must have `api`, `old`, `new`
- `review_patterns[]`: must have `pattern`, `source`, `finding`
- `human_overrides[]`: must have `phase`, `decision_id`, `override`
- `gaps[]`: must have `field`, `status`

---

### 4. `scripts/reconcile-tier1-staged.py` — Tier 1 Reconciliation

**Usage:**
```bash
python3 scripts/reconcile-tier1-staged.py [--dry-run]
```

**Behavior:**
1. Scan `$Z_HARNESS_PLAN_DIR/tier1-staged/` for concept directories
2. For each concept:
   a. Read `tier1-staged/<concept>/human.md` (staged)
   b. Read `docs/human/<concept>.md` (current)
   c. For each `<!-- AUTO-START: X -->...<!-- AUTO-END: X -->` section in current, replace with staged version
   d. Preserve everything outside delimiters
   e. Write merged version to `docs/human/<concept>.md`
   f. Same merge for `docs/llm/<concept>.json` (update entry_points, source_file, last_updated; preserve other fields)
3. Update `docs/llm/INDEX.json`:
   - For each touched concept: update `last_updated` timestamp, update `source_files`
   - Preserve all other fields
4. Run `scripts/regenerate-memories-flat.py`
5. If `--dry-run`, show diff only; don't write

**Merge strategy:** Latest-wins for overlapping staged updates (same concept touched by multiple tasks — last task's staged version applied).

**Exit codes:** 0=success, 1=merge conflict (unexpected — contents outside delimiters changed since staged), 2=write error

---

## Modified Files

### 5. `agents/implementer.md` — Extended Return Contract

**Change:** Add three new return fields after SUMMARY section.

**New fields in return block:**
```
RATIONALE:
  <1-3 sentences explaining why the chosen approach was taken,
   especially when it differs from what SPEC/PLAN specified>

TRIED: (optional — omit if no failed attempts)
  - <approach> — <why it failed>

DEVIATIONS: (optional — omit if implementation matches PLAN exactly)
  - <what differed from PLAN> — <why>
```

**Field contract:**
| Field | Required? | Validated by | Used for |
|---|---|---|---|
| `RATIONALE` | Yes | Reviewer (plausibility check) | Design rationale, tier2-context.json.decisions[] |
| `TRIED` | No (optional) | Reviewer (code consistency only) | Tried-and-failed sections, tier2-context.json.tried_and_failed[] |
| `DEVIATIONS` | No (optional) | Reviewer (validates against diff) | Migration guides, tier2-context.json.deviations[] |

**Reviewer validation:**
- RATIONALE: Check that code matches stated rationale (plausibility, not correctness)
- TRIED: Flag gross inconsistencies ("TRIED says thread pool but code still uses tokio::spawn") — cannot validate dead-code claims
- DEVIATIONS: Validate each claimed deviation against the diff (was the file added? dependency removed?)

---

### 6. `agents/reviewer.md` — Extended Validation Scope

**Change:** Add DEVIATIONS validation and RATIONALE plausibility check to reviewer brief.

**New sections in reviewer prompt:**
```
### DEVIATIONS validation
For each claimed deviation in the implementer's DEVIATIONS field:
  - Verify against git diff: was the claimed change actually made?
  - Flag if deviation is unverifiable or contradicts the diff

### RATIONALE plausibility
  - Does the code match the stated rationale?
  - Flag if rationale claims one approach but code follows another

### TRIED consistency (optional)
  - If TRIED entries exist: does the current code contradict any claimed failed approach?
  - Example: "TRIED says used tokio::spawn but code still imports tokio"
  - Report as MINOR only — reviewer cannot validate dead-code claims
```

**Existing contract preserved.** No changes to return format. New checks are additive within existing severity buckets (Blockers/Major/Minor).

---

### 7. `skills/z-implement-all/SKILL.md` — Tier 1 Dispatch + Context Accumulation

**Change 1: Tier 1 dispatch after reviewer passes (main loop step 7a)**

After reviewer passes (no blockers, no majors), insert Tier 1 step:

```
7a.1 Tier 1 doc sync:
  - git diff HEAD~1 --name-only → changed files
  - Spawn tier1-doc-updater (Flash) subagent with task diff + INDEX.json
  - Log result (CONCEPTS_TOUCHED, DRIFT_WARNINGS)
  - DRIFT_WARNINGS → log doc_drift event per affected slug
  - Failure: non-fatal; log tier1_failed event, continue
```

**Change 2: Implementer return parsing (main loop step 5)**

After implementer returns and before reviewer dispatch:
- Parse RATIONALE/TRIED/DEVIATIONS from return
- Call `append-tier2-context.py --phase implement --field tried_and_failed` if TRIED non-empty
- Call `append-tier2-context.py --phase implement --field deviations` if DEVIATIONS non-empty
- Call `append-tier2-context.py --phase implement --field breaking_changes` (derived from diff: detect changed public API signatures)

**Change 3: Human override capture at decision gates**

At each AskUserQuestion gate where human overrides a recommendation:
```
if user_choice != recommended:
    AskUserQuestion "Why <choice> over <recommended>? (press Enter to skip)"
    if reason provided:
        call append-tier2-context.py --phase implement --field human_overrides
```

**Change 4: Reconciliation in Finalize phase**

After all tasks complete, before deregister:
- If tier1-staged/ has content:
  - Run `scripts/reconcile-tier1-staged.py`
  - Log reconciliation result

---

### 8. `skills/z-plan/SKILL.md` — Tier 2 Context Initialization + Human Override Capture

**Change 1: Initialize tier2-context.json in Phase 3 (after synthesis)**

After writing `phase3-decisions-final.md`, append to tier2-context.json:
```bash
python3 scripts/append-tier2-context.py --phase plan --field decisions '<decisions JSON>'
python3 scripts/append-tier2-context.py --phase plan --field consultant_findings '<findings JSON>'
```
- `spec_summary`: derived from Phase 0 premise summary
- `plan_summary`: derived from approved decisions

**Change 2: Human override capture in Phase 5 (user approval)**

At the Phase 5 approval gate, after any override:
```bash
if user overrode a decision:
    AskUserQuestion "Why this choice? (press Enter to skip)"
    python3 scripts/append-tier2-context.py --phase plan --field human_overrides '<override JSON>'
```

**Prompt text for override capture:**
```
You chose [override] instead of the recommended [recommended].
Why? (press Enter to skip)
```

---

### 9. `commands/z-review-all.md` — Review Patterns Accumulation + Tier 2 Gate

**Change 1: Append review_patterns in Phase 5 (findings aggregation)**

After building `findings.md`, append aggregate patterns to tier2-context.json:
```bash
python3 scripts/append-tier2-context.py --phase review --field review_patterns '<patterns JSON>'
```
Extract: patterns that appeared across multiple tasks, consultant consensus/disagreement themes.

**Change 2: Finalize tier2-context.json + Tier 2 significance gate (after Phase 6, before Finalize)**

```bash
# Mark tier2-context.json as finalized
python3 -c "
import json, os
p = os.path.join(os.environ['Z_HARNESS_PLAN_DIR'], 'tier2-context.json')
d = json.load(open(p))
d['finalized'] = True
d['generated_at'] = '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
# Detect gaps (missing human_override reasons, etc.)
gaps = []
for override in d.get('human_overrides', []):
    if not override.get('reason'):
        gaps.append({'field': f'human_overrides[].reason', 'status': 'missing', 'note': f'Override for {override.get(\"decision_id\",\"?\")} missing reason'})
d['gaps'] = gaps
json.dump(d, open(p, 'w'), indent=2)
"

# Significance gate
SIGNIFICANT=false
python3 -c "
import json, os
d = json.load(open(os.path.join(os.environ['Z_HARNESS_PLAN_DIR'], 'tier2-context.json')))
consult = len(d.get('consultant_findings', [])) > 0
breaking = len(d.get('breaking_changes', [])) > 0
deviations = len(d.get('deviations', [])) > 0
if consult or breaking or deviations: print('true')
else: print('false')
" && SIGNIFICANT=true || SIGNIFICANT=false

if [ "$SIGNIFICANT" = true ]; then
    # Push notification + AskUserQuestion
    echo "Pipeline complete. Tier 2 context captured. Run /z-doc-rationale to produce design docs."
else
    echo "Pipeline complete. No significant design decisions. Tier 2 skipped."
fi
```

**Change 3: Tier 2 recommendation in Finalize push**

Add `/z-doc-rationale` to the post-pipeline recommendations (alongside /z-audit-plan, /z-test, /z-implement-all):
```
Recommended:
  /z-doc-rationale              — (recommended) produce ADRs, design rationale, migration guides
  /z-audit-plan                 — audit spec & tasks against codebase
  /z-implement-all              — (only if review findings need implementation)
```

---

### 10. `docs/llm/INDEX.json` — New Concept Entries

Add two new concepts:
```json
{
  "slug": "tier1-doc-updater",
  "source_files": ["agents/tier1-doc-updater.md", "scripts/reconcile-tier1-staged.py"],
  "last_updated": "<date>",
  "confidence": "high",
  "summary": "Tier 1 flash subagent for per-task mechanical doc sync. Reads task diff, reverse-lookups changed files → concepts via INDEX.json, applies surgical updates to AUTO-START/AUTO-END delimited machine-truth fields in human-tier and LLM-tier docs. Stages updates; reconciliation applies after all tasks."
},
{
  "slug": "tier2-doc-rationale",
  "source_files": ["commands/z-doc-rationale.md", "scripts/append-tier2-context.py"],
  "last_updated": "<date>",
  "confidence": "high",
  "summary": "Tier 2 narrative doc system. Accumulates tier2-context.json incrementally across pipeline phases (z-plan → z-implement-all → z-review-all). /z-doc-rationale command spawns Pro subagent to produce ADRs, design rationale, and migration guides. Significance-gated."
}
```

**Update existing concepts:**
- `implementer`: add RATIONALE/TRIED/DEVIATIONS to source_files
- `reviewer`: add DEVIATIONS validation to source_files
- `doc-updater`: add note about relationship to tier1-doc-updater

---

### 11. Existing Human-Tier Docs — Add Delimiter Markers

For each concept doc in `docs/human/<concept>.md`, add delimiter markers around machine-truth sections:

```markdown
## Key entry points

<!-- AUTO-START: entry-points -->
- `path/to/file.rs:42` — `symbol_name(args)` — Short description
<!-- AUTO-END: entry-points -->
```

Sections to delimit:
- `entry-points` — under `## Key entry points`
- `config-table` — under `## Configuration` (where applicable)
- `exports` — under `## Public API` or similar (where applicable)
- `design-decisions` — appended by Tier 2 (new section)

**Bootstrapping:** Run `/z-init-docs` with a new `--add-markers` flag, or apply markers as a one-time migration script in the implementation phase.

---

## Invariants & Edge Cases

### Cross-cutting invariants
1. **Never write to `docs/` from Tier 1 subagent** — staging only, reconciliation is the sole writer
2. **Never fabricate gap content** — documents ship with `status: missing` gaps
3. **Never touch `memories[]`** — memory authoring always goes through `/z-suggest-memory`
4. **Idempotent Tier 1** — re-running on same diff produces identical staged output
5. **Additive only** — AUTO-START/AUTO-END markers are additive; existing docs work without them

### Edge cases
- **Empty diff (no code changes):** Tier 1 returns `STATUS: nothing_to_update`
- **No concepts match changed files:** Tier 1 returns `STATUS: nothing_to_update`
- **Concept doc missing AUTO-START markers:** Tier 1 logs `markers_missing` event, skips concept
- **tier2-context.json doesn't exist at /z-doc-rationale time:** Abort with clear message
- **tier2-context.json not finalized:** Abort; tell user to complete pipeline
- **Multiple tasks touch same concept:** Latest-wins merge (last task's staged version applied)
- **Human presses Enter at "Why?" prompt:** Gap is recorded as `status: missing`, document ships with honest gap
- **Consultants unavailable (degraded):** tier2-context.json.consultant_findings[] is empty; significance gate may not fire (acceptable — false negative from degradation, not design)
- **Tier 1 reconciliation fails (docs outside delimiters changed):** Halt reconciliation; report conflict; user resolves manually or re-runs /z-maintain-docs

### DRY / KISS / SOLID compliance
- **DRY:** `append-tier2-context.py` is the single writer for tier2-context.json; `reconcile-tier1-staged.py` is the single writer for doc updates. No duplicate logic.
- **KISS:** Tier 1 is a Flash subagent with 4 output fields — no complexity creep. Tier 2 reads one JSON file. Two tiers, two concerns.
- **SOLID:** Single Responsibility: tier1-doc-updater syncs machine-truth; tier2-doc-rationale writes narrative. Open/Closed: new doc sections can be added via new AUTO-START markers without modifying Tier 1. Interface Segregation: implementer adds 3 optional fields to existing contract; reviewer adds 3 checks to existing brief — no new interfaces.
