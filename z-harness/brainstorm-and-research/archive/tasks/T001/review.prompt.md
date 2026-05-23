You are reviewing code that Claude just wrote for task T001: Add MODE: brainstorm + redefine MODE: research-review in codex-consultant.

Spec (excerpt from SPEC.md §"Consultant mode extensions"):

### MODE: brainstorm (both codex-consultant and gemini-consultant)
- Caller provides: topic, scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary).
- Consultant returns RAW (not the standard Recommendation/Reasoning/Tradeoffs/Additional considerations/Raw excerpt wrapper).
- Section schema (must produce all five, mark `<missing>` only if the model truly cannot):
  1. Framing
  2. Core hypothesis
  3. Risks
  4. Plan implications
  5. What would change my mind

### MODE: research-review (both consultants)
- Caller provides: research-note draft + original question + scaffolding.
- Consultant returns RAW. No standard wrapper.
- Sections returned:
  - Gaps (things the draft missed)
  - Errors (claims the draft made that appear wrong)
  - Missing constraints (constraints reviewer noticed that should be added)
- Explicit prohibition: must NOT recommend an approach. If consultant tries, the reviewer prompt explicitly instructs them to omit it.

Acceptance criteria:
- ## Modes gains brainstorm + research-review entries following existing pattern
- brainstorm: caller=topic+scaffolding; returns RAW 5-section block; NO standard return wrapper
- research-review: caller=research-note draft+question+scaffolding; returns RAW 3-section block; MUST NOT recommend approach; NO standard return wrapper
- existing modes (bundled-decisions, plan-review, light-fix, debug-hypotheses, doc-audit, test-cases) unchanged in semantics
- research-review redefined IN PLACE (not duplicated)

Diff (primary artifact):

diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
new file mode 100644
--- /dev/null
+++ b/agents/codex-consultant.md
@@ -0,0 +1,95 @@
---
name: codex-consultant
description: Consults Codex...
tools: Bash, Read, Grep, Glob
model: haiku
---

[file content as in the diff — full final state of the codex-consultant.md agent]

The relevant additions in ## Modes:

- **`brainstorm`** (Phase 2 of `/z-brainstorm`): caller provides topic + scaffolding (doc-fetcher synthesis + optional Explore findings + optional RESEARCH.md content or extractive summary). Ask Codex to return the five-section ideator block. Does NOT use the standard return wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Return RAW with exactly these sections (mark `<missing>` only if Codex truly cannot produce the section):
  1. Framing
  2. Core hypothesis
  3. Risks
  4. Plan implications
  5. What would change my mind
- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
  - Gaps (things the draft missed)
  - Errors (claims the draft made that appear wrong)
  - Missing constraints (constraints the reviewer noticed that should be added)
  Codex must NOT recommend an approach. Research is terrain-mapping, not direction-picking. The prompt must explicitly instruct Codex to omit any recommendation.

The "Building the prompt to Codex" and "Returning to the caller" sections still only reference bundled-decisions and plan-review modes (no instructions for raw return shape for brainstorm/research-review modes).

The "Archiving" section's SLUG variable example only lists `codex-<bundled-decisions|plan-review>`.

Scrutinize this code rigorously. Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, suggested fix.

OUTPUT BUDGET: under 8000 chars. Blockers and majors only. One finding per bullet. Two sentences max. If no blockers or majors, respond with exactly: `No blockers or majors found.` plus an optional 1-line note.
