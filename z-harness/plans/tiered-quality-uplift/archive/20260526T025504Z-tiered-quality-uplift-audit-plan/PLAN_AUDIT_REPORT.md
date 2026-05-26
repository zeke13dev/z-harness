# Plan Audit Report — tiered-quality-uplift

- **Date (UTC):** 2026-05-26T02:55Z
- **Slug:** tiered-quality-uplift
- **Run ID:** 20260526T025504Z-tiered-quality-uplift-audit-plan

## Summary

The plan is structurally sound: zero new agents, sibling-plan layout reuses `/z-implement-all --tasks=` verbatim, MANIFEST as resume authority. The core orchestration design is buildable as-is. However, several **reality-check blockers** would cause the implementation to fail at dispatch time. These are concentrated in TASKS T003 / T004 / T008 and the SPEC dispatch sections. Fix four blockers and six majors before implementation; minors can be polished during T001–T008.

The cross-LLM consultants (Codex + Gemini) **agreed on every blocker** flagged in the reality check, with no disagreement on severity, and added one new blocker (T002 edit-and-confirm gate mechanism).

## Reality Check findings

### BLOCKER — Hardcoded provider-specific agent names

**Location:** SPEC.md L100–L102, L121, L123, L126; PLAN.md L4, L9, L23, L30; TASKS.md T003, T004.

**Evidence:** All dispatch calls use `subagent_type="z-harness:gemini-consultant"`, `subagent_type="z-harness:codex-consultant"`, `subagent_type="z-harness:codex-reviewer"`. None of those agents exist. Actual agents are `consultant-primary`, `consultant-secondary`, `reviewer` (provider-resolved at dispatch via `scripts/resolve-provider.sh`). The in-repo convention per `commands/z-audit.md:138-148` is bare `subagent_type="consultant-primary"` — no `z-harness:` namespace prefix.

**Recommendation:** Global rename throughout SPEC/PLAN/TASKS: `z-harness:gemini-consultant` → `consultant-primary`, `z-harness:codex-consultant` → `consultant-secondary`, `z-harness:codex-reviewer` → `reviewer`. Drop hardcoded "Gemini"/"Codex" labels from descriptions.

### BLOCKER — `auditor` agent contract mismatch (`rubric_path` not inline content)

**Location:** SPEC.md L121; TASKS.md T004 L48.

**Evidence:** SPEC prescribes inlining STYLE.md content into the auditor prompt as a `rubric:` field. Per `agents/auditor.md:11`, the auditor's input contract is `rubric_path` (a file path), and the auditor reads the file itself.

**Recommendation:** Pass `rubric_path: <abs path to STYLE.md>` when STYLE.md is present and dimension ∈ {cleanliness, design}; empty `rubric_path` otherwise (auditor's existing generic-rubric fallback). Remove the inline content injection from T004 and SPEC.

### BLOCKER — JS regex syntax in path computation (TASKS T003)

**Location:** TASKS.md T003 L34.

**Evidence:** `$Z_HARNESS_PLAN_DIR.replace(/<slug>$/, '<slug>-cross-cutting')` is JavaScript regex syntax. Cannot execute in bash or python orchestration.

**Recommendation:** Replace with concrete bash, e.g. `CROSS_DIR="$(dirname "$Z_HARNESS_PLAN_DIR")/${Z_HARNESS_SLUG}-cross-cutting"`, or python equivalent. Update T003 acceptance to verify the synthetic dir lands at the correct sibling path.

### BLOCKER — `skills/z-audit/SKILL.md` does not exist

**Location:** SPEC.md L217; TASKS.md T008 L95.

**Evidence:** SPEC and T008 instruct the implementer to mirror `skills/z-audit/SKILL.md`. That file does not exist (`ls skills/` shows no `z-audit/` dir). Listed skills: `z-amend, z-brainstorm, z-debug, z-do, z-implement-all, z-implement-next, z-improve, z-init-docs, z-maintain-docs, z-plan, z-plan-light, z-plan-split, z-research, z-review-all, z-stats, z-suggest-memory, z-test, z-update`.

**Recommendation:** Retarget pattern to an existing skill, e.g. `skills/z-improve/SKILL.md` or `skills/z-research/SKILL.md`. Update T008 description + acceptance.

## Design & Style findings

### MAJOR — `docs/llm/z-uplift.json` has no schema anchor

**Location:** SPEC.md L194; TASKS.md T008.

**Evidence:** `docs/llm/z-audit.json` (the implied reference) does not exist. Existing concept JSONs that can anchor: `docs/llm/z-fix.json`, `docs/llm/z-update.json`, `docs/llm/style-init.json`.

**Recommendation:** Update T008 to: "Use `docs/llm/style-init.json` (or `z-update.json`) as the canonical-schema reference. Mirror its top-level keys."

### MAJOR — `--refresh-component` deletes user-edited TASKS.md silently

**Location:** TASKS.md T006 L78.

**Evidence:** "delete its REPORT.md and TASKS.md (preserve SPEC/PLAN)" runs without backup. If user has hand-edited TASKS.md to triage findings, those edits are destroyed.

**Recommendation:** Before deletion, move REPORT.md + TASKS.md to `<plan-dir>/archive/<RUN>/refreshed/`. Atomic move (`os.replace`). Add T006 acceptance bullet verifying the backup path is created and populated.

### MAJOR — T010 smoke-test cleanup destroys artifacts before user inspects

**Location:** TASKS.md T010 L132.

**Evidence:** T010 is INTERACTIVE but auto-cleans the plan dir post-run. User wanting to inspect `events.jsonl`, MANIFEST, REPORT loses them.

**Recommendation:** Drop the auto-cleanup line; document manual cleanup ("`rm -rf z-harness/plans/tiered-quality-uplift-smoke-*` after inspection"). Or convert to an explicit final AskUser ("keep / delete").

### MAJOR — `auditor` agent `rubric_path` injection details (companion to the BLOCKER above)

Already covered above; the design audit confirms passing a path is the standard contract and the SPEC's prompt-format invention was the bug.

### MAJOR — `[i] implementing` resume branch missing from T006 acceptance

**Location:** TASKS.md T006 L82; SPEC.md L237.

**Evidence:** The state machine in SPEC.md L158 includes `[i] implementing`; SPEC L237 enumerates the AskUser branch (resume / mark-done / mark-skipped / abort). T006's acceptance only enumerates `[~] auditing` and `[a] audited` cases. The implementer could derive from SPEC L237, but the acceptance gap risks silent omission.

**Recommendation:** Add T006 acceptance bullet: "Resume detects `[i] implementing` and runs the SPEC L237 AskUser branch."

### MAJOR — STYLE gate halt has no documented resume instruction

**Location:** SPEC.md L31; TASKS.md T001 L10.

**Evidence:** SPEC says "halt the run cleanly" when user picks `/z-style-init` but doesn't explicitly say "re-invoke `/z-uplift` afterward". UX gap.

**Recommendation:** Update SPEC L31 halt message: "After running `/z-style-init`, re-invoke `/z-uplift` to continue."

### MAJOR — "edit-and-confirm" gate option has no mechanism

**Location:** TASKS.md T002 L21; SPEC.md L33.

**Evidence:** AskUser offers "proceed / abort / edit-and-confirm" but no path described for how the user edits COMPONENTS.md and re-confirms without re-invoking `/z-uplift`.

**Recommendation:** Drop the option; keep only "proceed / abort". User can abort, edit, re-invoke (the orchestrator will re-detect and show the same AskUser).

### MAJOR — Entry file heuristic for cross-cutting source map is undefined

**Location:** SPEC.md L101; TASKS.md T003 L31.

**Evidence:** "each component's entry file" is named but never resolved. README.md? src/lib.rs? package.json? Implementation will be non-deterministic.

**Recommendation:** Define explicitly in SPEC: "Entry file per component (in priority order): README.md → src/lib.rs → src/main.rs → __init__.py → package.json → first non-test source file by lexicographic order → component root itself."

### MAJOR — `--dimensions` default omits `perf` without surfaced rationale

**Location:** SPEC.md L46; TASKS.md T001 L8.

**Evidence:** Default `correctness,cleanliness,design`. Rationale "to keep uplift scope bounded" appears in SPEC body, but a user reading T001 won't see it. Risk of "is this an oversight?" confusion.

**Recommendation:** Add inline comment to the flag definition: "`--dimensions` default omits `perf` to bound cost; pass `--dimensions=correctness,cleanliness,design,perf` for perf audits."

### MAJOR — T004 text-grep dependents reporting risks false confidence

**Location:** TASKS.md T004 L51; SPEC.md L209.

**Evidence:** On bail, `git grep` for component basename surfaces "Dependents" but misses reflection / string imports. Misleading label.

**Recommendation:** Update label in REPORT.md and MANIFEST.md to "Potential dependents (text-grep — incomplete; validate manually for critical APIs)".

## Adversarial Consult findings (Codex + Gemini, both agree)

### MINOR — `--components=<file>` lacks path validation

**Recommendation:** Resolve to abspath; verify path is within repo root; reject if it escapes via symlink or `..`. Hardening.

### MINOR — T007 telemetry acceptance is metric-for-metric's-sake

**Evidence:** "grep returns ≥10 distinct event names" is a tautology.

**Recommendation:** Reframe as: "every event listed in SPEC.md L163-169 fires at its named checkpoint; every AskUser is bracketed by `user_wait_start`/`user_wait_end`."

### MINOR — Per-component-context matching by free-text is fragile

**Location:** SPEC.md L121; TASKS.md T004 L47.

**Recommendation:** Require cross-cutting consultant to emit explicit `component: <slug>` markers (already in CROSS-CUTTING.md schema implicitly via "affects `<component-name>`"). Strengthen T004 to match on exact slug from MANIFEST, not prose.

### MINOR — Build-break mitigation language is too optimistic

**Location:** SPEC.md L208–209.

**Recommendation:** Add explicit gotcha: "Processing `<slug>-cross-cutting` first mitigates but does not eliminate build-break risk between per-component implements. Operators should expect to manually resolve transient build failures."

### MINOR — Concurrent `/z-uplift` invocation not addressed

**Recommendation:** Add SPEC invariant: "Only one `/z-uplift` invocation per repo at a time; concurrent invocations race on MANIFEST.md."

### MINOR — Slug collision and `--components=<file>` paths are untested

**Location:** TASKS.md T002 / T010.

**Recommendation:** Add T010 acceptance cases (or a follow-up T010b): one collision repo + one `--components=<file>` invocation.

### MINOR — Doc-staleness gate behavior not specified

**Location:** SPEC.md L30.

**Recommendation:** Either say "same shape as `/z-plan` Setup step 8" (cite line) or expand to one paragraph if behavior diverges.

### MINOR — Inline audit duplication has no drift detector

**Location:** PLAN.md L30; SPEC.md L200.

**Recommendation:** Document the exit criterion ("extract when third caller appears") prominently in the `z-uplift.json` invariants block; no CI check needed now.

## Consensus vs Disagreement

- **Both consultants + reality check agree** on all four blockers and all seven majors. No conflicting positions on severity.
- **Pushback applied:**
  - Phase 2's "fold `--retry-bailed` and `--refresh-component` into one flag" → **rejected** (both consultants prefer distinct flags for explicit semantics).
  - Phase 2's "telemetry envelope is heavy" → **kept rich**, only the T007 acceptance is reframed.
  - "STYLE gate halt instruction" classification → Codex MAJOR, Gemini BLOCKER → settled as **MAJOR** (one-line doc fix, not compile-blocking).
  - "[i] implementing resume" classification → Codex BLOCKER, Gemini BLOCKER → settled as **MAJOR** (SPEC L237 already enumerates behavior; the gap is in T006 acceptance, not in the design).
  - "edit-and-confirm" classification → Codex MAJOR, Gemini BLOCKER → settled as **MAJOR** (UX ambiguity, not compile-blocking).

## Actionable Recommendations

**Before /z-implement-all:**

1. **BLOCKER fixes (4):**
   - Rename `z-harness:gemini-consultant` → `consultant-primary`, `z-harness:codex-consultant` → `consultant-secondary`, `z-harness:codex-reviewer` → `reviewer`. Drop the `z-harness:` namespace prefix.
   - Switch auditor rubric injection to `rubric_path` (a file path), not inline content.
   - Replace JS regex in T003 with a concrete bash/python expression for the synthetic cross-cutting plan dir path.
   - Retarget the skill-pattern reference in T008 from `skills/z-audit/SKILL.md` (missing) to an existing skill like `skills/z-improve/SKILL.md`.

2. **MAJOR fixes (8):**
   - Schema anchor for `docs/llm/z-uplift.json` (point at `style-init.json` or `z-update.json`).
   - Backup REPORT.md + TASKS.md before `--refresh-component` deletes them.
   - Drop or convert T010 auto-cleanup to an explicit AskUser.
   - Add T006 resume branch for `[i] implementing`.
   - Add STYLE gate resume instruction ("re-invoke `/z-uplift` afterward").
   - Drop "edit-and-confirm" AskUser option (keep proceed / abort).
   - Define entry-file heuristic for cross-cutting source map.
   - Surface `--dimensions` default-omits-perf rationale at the flag definition.
   - Label text-grep dependents reporting as "potential / incomplete".

3. **MINOR (polish during T001–T008, not blockers):**
   - `--components=<file>` path validation.
   - T007 telemetry acceptance reframed away from count metric.
   - Per-component-context matching by slug, not free-text.
   - Build-break mitigation language updated.
   - "Only one `/z-uplift` per repo at a time" invariant.
   - Add T010 acceptance for slug collision + `--components=<file>` escape hatch.
   - Doc-staleness gate behavior specified or cite source.
   - Document drift-monitoring exit criterion for inline `/z-audit` duplication.

**Suggested next step:** Run `/z-amend` with this report as input to apply the blocker + major fixes in-place. Minors can be folded into T001–T008 implementations.
