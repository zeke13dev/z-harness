# SPEC — z-audit-plan

This specification outlines the files and content changes to implement the `/z-audit-plan` plan audit pipeline.

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| none — fresh /z-plan run | n/a | n/a |

---

## Proposed Changes

### [NEW] `commands/z-audit-plan.md`

Defines the core `/z-audit-plan` command. It runs a read-only, multi-phase plan audit.

#### Frontmatter
```yaml
---
description: Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md.
argument-hint: [--slug <slug>]
---
```

#### Pipeline Phases
1. **Phase 0 — Setup**
   - **Slug Discovery:** Scan `z-harness/plans/` and legacy `z-harness/` for subdirectories containing `TASKS.md` and `SPEC.md`.
     - Single candidate: auto-select.
     - Multiple: use `AskUserQuestion` to pick.
     - `--slug <slug>` argument overrides discovery.
   - **Environment:** Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash scripts/plan-path.sh resolve_plan_path $Z_HARNESS_SLUG)`. Define `$BASE = $Z_HARNESS_PLAN_DIR`.
   - **Run ID:** `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>-audit-plan`.
   - **Logging & Telemetry:** Log `plan_audit_start` event to metrics.
   - **Docs Grounding:** If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` subagent to fetch matched concepts to guide reference verification.

2. **Phase 1 — Reality Check (Reference Verification)**
   - Parse `$BASE/SPEC.md` and `$BASE/TASKS.md` for references to existing entities:
     - File paths, directory structures.
     - Function, class, type, and symbol names.
     - Database tables, schemas, or columns.
     - Configuration keys/files or CLI flags.
   - For all entities described as already present ("MUST EXIST NOW"), execute a fast, read-only search using `Read`/`Grep`/`Glob` to confirm they exist exactly as described.
   - Check if any newly proposed files clash with existing codebase files.
   - Write Reality Check verification results to `$BASE/archive/$RUN/phase1-reality.md`.

3. **Phase 2 — Best Practices & Design Audit**
   - Evaluate plan architecture, modules, boundaries, and dependencies against standard best practices:
     - KISS, DRY, and SOLID principles.
     - The project's `STYLE.md` rules (if it exists).
     - Potential over-engineering or premature abstractions.
     - Performance regressions (allocations, database n+1 queries, locking).
     - Security vulnerabilities (injection, unvalidated inputs, data leakage).
   - Write Design Audit results to `$BASE/archive/$RUN/phase2-design.md`.

4. **Phase 3 — Adversarial Cross-LLM Review**
   - Spawn parallel consultants via the provider registry:
     ```
     Agent(
       subagent_type="consultant-primary",
       description="Adversarial plan audit review (Gemini) for plan <slug>",
       prompt="MODE: plan-audit-review\n\nPlan SPEC:\n<SPEC.md>\n\nPlan PLAN:\n<PLAN.md>\n\nPlan TASKS:\n<TASKS.md>\n\nReality Check & Design notes:\n<reality.md + design.md>\n\nAct as a highly critical, adversarial 'Senior Nitpicker'. Identify hidden bugs, race conditions, edge cases, missing tests in acceptance criteria, security flaws, style drift, or over-engineering. For each finding, provide severity (BLOCKER / MAJOR / MINOR), location, and recommendations."
     )
     Agent(
       subagent_type="consultant-secondary",
       description="Adversarial plan audit review (Codex) for plan <slug>",
       prompt="MODE: plan-audit-review\n\n<same prompt>"
     )
     ```
   - Archive transcripts under `$BASE/archive/$RUN/transcripts/`.

5. **Phase 4 — Merge and Synthesize Findings**
   - Once both consultants return, merge findings from all phases.
   - Apply the **"one-reason-this-might-be-wrong"** rule to filter out speculative, pedantic, or false-positive findings.
   - Write the unified `$BASE/PLAN_AUDIT_REPORT.md` (and a copy under the archive directory):
     - Metadata (Date, Slug, Run ID, checked files).
     - Summary (Actionable high-level takeaways).
     - Reality Check Findings (Stale references, clashes, hallucinations).
     - Design & Best Practices Findings (SOLID/KISS violations, style drift, perf).
     - Adversarial Consult Findings (Logic gaps, edge cases, missing tests).
     - Recommendations / Next Steps.

6. **Phase 5 — User Gate & Action**
   - Present a concise findings summary (focusing on BLOCKER and MAJOR findings) and ask via `AskUserQuestion`:
     - **Amend Plan (Run z-amend)** — Propose to amend plan artifacts interactively to address findings.
     - **Proceed as-is** — Accept findings as acceptable design trade-offs and proceed.
     - **Reject & Re-plan** — Reject the current plan and rerun `/z-plan`.
   - Log `plan_audit_end` event with summary counts.

---

### [NEW] `skills/z-audit-plan/SKILL.md`

Defines the workspace skill version of the plan audit pipeline.

#### Frontmatter
```yaml
---
name: z-audit-plan
description: Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md.
---
```

#### Body
Contains the exact same markdown body logic as `commands/z-audit-plan.md` to ensure the skill operates identically to the core command.

---

### [MODIFY] `commands/z-plan.md`

Update the recommendations block in Phase 9 to suggest `/z-audit-plan` as a key intermediate step.

```diff
 Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
 ```
 Plan complete. <N> tasks queued.
 
 Recommended:
   /compact          — free planning context before next phase
+  /z-audit-plan     — (recommended) audit spec & tasks against codebase reality and best practices
   /z-test           — (optional, recommended for risky / financial code) draft semantic test cases before implementation
   /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
 ```
```

---

### [MODIFY] `exports/agy/agy-plugin.yaml`

Register the new command and skill inside the export configuration.

Under `workflows:`:
```yaml
  - id: z-audit-plan
    source: commands/z-audit-plan.md
    output: .agent/workflows/z-audit-plan.md
    description: "Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md."
```

Under `skills:`:
```yaml
  - id: z-audit-plan
    source: skills/z-audit-plan/SKILL.md
    output: .agent/skills/z-audit-plan/SKILL.md
    description: "Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md."
```
