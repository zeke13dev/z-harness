MODE: bundled-decisions

## Context: Fanout-Escalate-Primitive v1a ("scope-probe")

We are planning v1a of a new Haiku subagent called `scope-probe`, which will run as Phase 0 of `/z-audit` and `/z-brainstorm`. Its job is to classify the scope of a given planning or audit task (LIGHT, MEDIUM, or HEAVY) and discover a natural axis for parallelization when escalation is warranted.

### Deliverables for v1a
1. scope-probe agent (Haiku, read-only, follows frontmatter pattern)
2. SCOPE.json artifact (versioned output format)
3. Calibration harness replaying 5-6 historical runs
4. Integration into /z-audit and /z-brainstorm command flows
5. (v1b will defer deletions of existing escalation chains)

### Codebase patterns to respect
- **Haiku agent frontmatter:** `name`, `description`, `tools: Read, Grep, Glob`, `model: haiku`. Examples: agents/planning-router.md, agents/complexity-classifier.md, agents/doc-fetcher.md.
- **Output contracts:**
  - planning-router: strict line-prefix (STATUS:/RECOMMENDED:/ROUTE_CLASS:/CONFIDENCE:/REASON_CODES:/REASON:)
  - review-agent: single fenced JSON block, no prose before/after
- **Archive structure per run:** events.jsonl (NDJSON), manifest.json (with slug/run/status/tasks_total/tasks_complexity/decisions_total/consultations/framing), phaseN-*.md checkpoints, transcripts/.
- **z-audit Phase 1:** collects dimensions via AskUserQuestion; no formal Phase 0 today.
- **z-brainstorm Phase 1:** scaffolding step; Phase 2 ideator dispatch; Phase 3 anti-bias check. No formal Phase 0 today.

---

## Five Consult-Flagged Decisions

### D1: Output contract shape
**Decision:** What parseable contract does scope-probe emit?

**Options:**
- (a) Strict line-prefix contract like planning-router (STATUS:/MODE:/AXIS:/CONFIDENCE:/REASON_CODES:/REASON: + possibly fenced data block)
- (b) Fenced JSON block only (like review-agent: one JSON block, no prose around it)
- (c) Hybrid: line-prefix headers (STATUS/MODE/AXIS/CONFIDENCE/REASON_CODES) + fenced JSON for the chunks array below the headers

**Tentative call:** (c) hybrid

**Context for reasoning:**
- planning-router's line-prefix is ideal for routing decisions because downstream code calls `grep` on it.
- review-agent's JSON is ideal for structured memory candidates.
- scope-probe must emit both a classification decision (MODE: LIGHT/MEDIUM/HEAVY) and structured chunk metadata (list of detected chunks/seams, per-chunk task-count estimate, axis labels).
- The chunks array is complex and benefits from JSON structure; the routing decision itself is simple and benefits from grep-able prefixes.

---

### D2: SCOPE.json schema + location
**Decision:** Where does SCOPE.json live and how is it versioned?

**Options:**
- (a) Per-run only: z-harness/<slug>/archive/<RUN>/SCOPE.json. Immutable. No live copy.
- (b) Live only: z-harness/<slug>/SCOPE.json (overwritten each run). Immutable archive copies are left to the orchestrator's run-capture mechanism (events.jsonl, etc.).
- (c) Both: live file at z-harness/<slug>/SCOPE.json + namespaced archive at z-harness/<slug>/archive/<RUN>/SCOPE.json. Live file is keyed by host command (e.g., SCOPE-audit.json vs SCOPE-brainstorm.json) to avoid collisions when both commands run against the same slug.

**Tentative call:** (c) both, namespaced

**Context for reasoning:**
- v1a will integrate scope-probe into /z-audit and /z-brainstorm. Same slug may be audited one day and brainstormed another.
- Live file serves as a "latest scope decision" cache for downstream tooling (e.g., if the implementer wants to know the discovered axis).
- Archived copy preserves the per-run scope decision for forensics and calibration.
- Namespacing (SCOPE-audit.json vs SCOPE-brainstorm.json) prevents /z-audit's scope decision from being clobbered by /z-brainstorm (or vice versa) on the same slug.

---

### D4: Axis discovery heuristics
**Decision:** How does scope-probe pick a natural axis for parallelization?

**Options:**
- (a) Free-form invention: scope-probe invents an axis based purely on codebase structure (e.g., "per-strategy-component" inferred from directory layout).
- (b) Caller-supplied taxonomy only: scope-probe only uses axes the caller explicitly provided in a config or prompt.
- (c) Hybrid: scope-probe starts with a caller-supplied taxonomy (if present), then supplements with structural evidence from the codebase (per-component, per-dimension, per-file-type, etc.) to arrive at the best axis.

**Tentative call:** (c) hybrid

**Context for reasoning:**
- Free-form (a) risks inventing axes that don't match the user's mental model of the codebase.
- Caller-supplied-only (b) is too rigid; if no taxonomy was supplied, scope-probe has no signal.
- Hybrid (c) respects the user's intent while discovering structure automatically. The orchestrator can pass an optional `preferred_axes` list; scope-probe weights that list but also considers structural seams.

---

### D7: Calibration replay protocol
**Decision:** How do we validate scope-probe's classification and axis discovery against historical archive data?

**Options:**
- (a) LLM-replay all 5-6 historical runs: re-run scope-probe against each archived run's original topic/target + context, collect decisions, compare to ground truth.
- (b) Deterministic-replay (Python heuristics only): encode the classification rules as Python functions (task count thresholds, complexity heuristics, etc.), replay against archived manifest data, compare to ground truth.
- (c) Sample: 2 LLM + 4 deterministic — hybrid: use LLM on 2 representative runs, deterministic rules on the rest for speed.

**Tentative call:** (a) LLM-replay all 5-6 historical runs

**Context for reasoning:**
- (a) is most faithful to the actual agent behavior. Calibration is testing the agent itself, not a mock.
- (b) is faster but risks missing edge cases the LLM discovers.
- (c) saves cost but introduces asymmetry in the calibration dataset.
- Given that scope-probe is a Phase 0 gate, fidelity matters more than speed. Cost for 5-6 runs is acceptable.

---

### D8: Ground-truth label
**Decision:** What defines "correct" when comparing scope-probe's classification (LIGHT/MEDIUM/HEAVY) to historical runs?

**Options:**
- (a) tasks_total only: ground truth is the number of tasks eventually created. LIGHT = ≤5 tasks, MEDIUM = 6-20 tasks, HEAVY = >20 tasks.
- (b) Mid-flight escalation events only: ground truth is whether the run actually escalated (spawned multiple chunks) or stayed single-threaded. Matches presence of fan-out events in events.jsonl.
- (c) Combined rubric: ground truth is tasks_total + tasks_complexity + escalation events. Weights all three signals.

**Tentative call:** (c) combined rubric

**Context for reasoning:**
- (a) is simplest but ignores complexity: a task requiring 50 hours of parallelizable work should escalate even if it results in few tasks.
- (b) is faithful to the actual runtime behavior but ignores pre-escalation estimate quality (maybe escalation was late and suboptimal).
- (c) is most robust: if all three signals agree, classification is high-confidence. If they disagree, it's a calibration miss worth investigating.

---

## Your Task

For EACH of the 5 decisions above (D1, D2, D4, D7, D8), provide:

1. **Your recommended option** (pick a, b, or c).
2. **Reasoning** (≤3 sentences of concrete logic, grounded in the codebase patterns and the deliverable's role).
3. **Interaction warnings** — if this decision affects or conflicts with any other decision in this bundle, flag it. E.g., "D1 and D2 interact: if D1 chooses (b) JSON-only, D2's namespacing strategy must accommodate JSON schema versioning."

At the end, add a **"Cross-cutting concerns"** section (optional) if you see any systemic issues (e.g., "all five decisions lean toward complexity; consider a Phase 0.5 simplification pass") or opportunities (e.g., "D7 calibration can double as a regression test suite for scope-probe").

Return your recommendations in a structured format clear enough for the orchestrator to act on, but do not write code or propose pseudo-implementation.
