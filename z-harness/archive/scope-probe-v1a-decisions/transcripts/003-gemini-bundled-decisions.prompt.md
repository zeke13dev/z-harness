MODE: bundled-decisions

# Context: fanout-escalate-primitive v1a planning

We're planning v1a of "fanout-escalate-primitive" — a new Haiku `scope-probe` subagent that runs as Phase 0 of `/z-audit` and `/z-brainstorm`. It classifies the topic as LIGHT (narrow single run) / MEDIUM (normal single run) / HEAVY (fan out N parallel chunks; main thread reconciles). Discovers a natural axis (per-component, per-dimension, etc) from codebase structure. Returns a parseable manifest. v1a includes: scope-probe agent + SCOPE.json artifact + calibration harness replaying historical archive runs + /z-audit + /z-brainstorm integrations.

## Codebase patterns (grounding context)

**Haiku agent frontmatter pattern:**
```yaml
---
name: scope-probe
description: Phase 0 scope classifier for fan-out escalation
tools: Read, Grep, Glob
model: haiku
---
```

**planning-router output contract (line-prefix only):**
```
STATUS: <value>
RECOMMENDED: <value>
ROUTE_CLASS: <value>
CONFIDENCE: <value>
REASON_CODES: <comma-separated>
REASON: <one line>
```

**review-agent output contract (single fenced JSON block):**
```json
[
  {
    "candidate_kind": "...",
    "type": "...",
    "text": "...",
    "tags": [...],
    "suggested_concept_slug": "...",
    "evidence_citations": [...],
    "rationale": "..."
  }
]
```

**Archive structure (per run):**
- `z-harness/archive/$RUN/events.jsonl` (NDJSON log)
- `z-harness/archive/$RUN/manifest.json` (slug/run/status/tasks_total/tasks_complexity/decisions_total/consultations/framing)
- `z-harness/archive/$RUN/phaseN-*.md` (checkpoints)
- `z-harness/archive/$RUN/transcripts/` (consult artifacts)

**Existing `/z-audit` contract (commands/z-audit.md:1-50):**
- No formal Phase 0; Phase 1 collects dimensions via AskUserQuestion
- Phase 2: parallel auditor dispatch (one per dimension)
- Phase 4: bundled Gemini+Codex consult
- Hard rules: read-only, codex safety gate on TASKS.md, always emit cross-LLM consult

**Existing `/z-brainstorm` contract (commands/z-brainstorm.md:42-60):**
- Plan Route Check between Phase 1 scaffolding and Phase 2 ideator dispatch
- Phase 2: parallel ideator dispatch (Claude Sonnet + Codex + Gemini, identical scaffolding)
- Phase 3: anti-bias synthesis, user choice
- Uses doc-fetcher (Haiku) for INDEX.json synthesis in Phase 1a

## Five consult-flagged decisions

### D1: Output contract shape
**Decision:** What parseable contract does scope-probe emit?

**Options:**
- **(a) Strict line-prefix** contract like planning-router: `STATUS: ... | MODE: ... | AXIS: ... | CONFIDENCE: ...`
- **(b) Fenced JSON block** (like review-agent): single `{ status, mode, axis, chunks: [] }`
- **(c) Hybrid:** line-prefix headers (STATUS/MODE/AXIS/CONFIDENCE/REASON_CODES) + fenced JSON for the chunks array

**Tentative call:** (c) hybrid. Cheap line-prefix grep for top-level decision; JSON for the chunks structure.

**Load-bearing context:**
- planning-router clients expect line-prefix parseable output and actually grep for `STATUS:` lines
- review-agent clients expect fenced JSON blocks and parse them directly
- chunks array must carry per-chunk detail: name, predicted_cost, suggested_concurrency, file_example

---

### D2: SCOPE.json schema + location
**Decision:** Where does SCOPE.json live? Single-file or per-run?

**Options:**
- **(a) Per-run only:** `z-harness/<slug>/archive/<RUN>/SCOPE.json`
- **(b) Live only:** `z-harness/<slug>/SCOPE.json` (overwritten each run)
- **(c) Both:** live + archived copy

**Tentative call:** (c) both. Plus D14 namespacing: live file keyed by host command so `/z-audit` and `/z-brainstorm` runs against the same slug don't clobber each other.

**Load-bearing context:**
- Other agents (e.g., implementer) may want to read the "current live scope" mid-flight without replaying the probe
- Audit trail / reproducibility requires per-run archival
- Example live namespacing: `z-harness/<slug>/SCOPE-audit.json` vs. `SCOPE-brainstorm.json`

---

### D4: Axis discovery heuristics
**Decision:** How does scope-probe pick a natural axis?

**Options:**
- **(a) Free-form:** parse topic → walk dirs 2 levels → count seams → query doc-fetcher → emit any axis name
- **(b) Caller-supplied taxonomy:** host command passes `axis_taxonomy: [<allowed axes>]`; scope-probe picks from that list only
- **(c) Hybrid:** caller-supplied taxonomy + structural-seam evidence determines which axis wins

**Tentative call:** (c) hybrid. Prevents scope-probe inventing nonsense axes for a given host command; keeps it extensible.

**Load-bearing context:**
- `/z-audit` taxonomies might be: [correctness, perf, cleanliness, design] (dimensions)
- `/z-brainstorm` taxonomies might be: [vendor, domain, technology-layer, risk-profile]
- If no taxonomy supplied, scope-probe should fail fast with a clear error, not guess

---

### D7: Calibration replay protocol
**Decision:** Does the calibration harness use the LLM or deterministic heuristics?

**Options:**
- **(a) LLM-replay all 5-6 historical runs** (~6 Haiku calls, one per run in archive)
- **(b) Deterministic-replay:** apply scope-probe heuristics in Python, no LLM
- **(c) Sample:** 2 LLM-replay + 4 deterministic

**Tentative call:** (a) LLM-replay all. We need to validate Haiku tier's actual classification quality, not just the heuristic.

**Load-bearing context:**
- Historical archive runs have events.jsonl with deterministic ground truth (tasks_total, tasks_complexity, mid-flight escalations)
- Haiku cost for one scope-probe call is ~500-1000 tokens
- Full replay of 5-6 runs is ~5-6 Haiku calls, well within budget for a one-time calibration harness
- Deterministic heuristics alone won't catch edge cases where Haiku's semantic understanding of the topic differs from static file counts

---

### D8: Ground-truth label for calibration
**Decision:** What does the harness compare scope-probe's classification against?

**Options:**
- **(a) tasks_total from manifest.json:** ≤5 LIGHT / 6-15 MEDIUM / ≥16 HEAVY
- **(b) Mid-flight escalation events:** `plan_route_decision → MEDIUM`; `escalation.md → HEAVY`; neither → LIGHT
- **(c) Combined rubric:** tasks_total AND tasks_complexity AND escalation events, with a documented scoring function

**Tentative call:** (c) combined rubric, documented in harness for reproducibility.

**Load-bearing context:**
- tasks_total alone is too crude; a run with 8 tasks but 3 CRITICAL bugs is not the same as 8 simple refactors
- Mid-flight escalation is the human signal but it's sparse (not all runs have it)
- Combined rubric allows us to weight: `base_score = (tasks_total / 5) + (max_severity * 0.5) + (escalation_flag * 2)` → LIGHT/MEDIUM/HEAVY by threshold
- Must document the scoring function in the harness so future calibrations remain reproducible

---

## Instructions for Gemini

For EACH of the 5 decisions (D1, D2, D4, D7, D8):

1. **Give your recommended option** — state which of (a), (b), (c) is best.
2. **≤3 sentences reasoning** — why that option wins on tradeoffs, simplicity, and alignment with the codebase patterns shown.
3. **Interaction warnings** — any cross-cutting concerns or dependencies between this decision and others in the bundle.

**End with a "cross-cutting concerns" section** if you see any overarching themes (e.g., all decisions should prefer JSON over line-prefix, or there's a tension between "all runs archived" and "live read efficiency").

---

## Ground truth about output contracts in this codebase

The codebase **actually uses BOTH patterns:**
- planning-router uses **line-prefix** (STATUS:/RECOMMENDED:/etc.) because its clients grep for those lines
- review-agent uses **fenced JSON** because its clients parse JSON directly
- There is no precedent for a "hybrid" contract in this codebase yet

Gemini should weigh whether a hybrid is worth the added complexity, or whether scope-probe should pick ONE pattern and stick to it.
