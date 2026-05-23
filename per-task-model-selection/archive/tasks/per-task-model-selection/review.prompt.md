You are reviewing a META change to the z-harness markdown harness (slash-command + skill + subagent markdown files). The "code" is markdown that drives Claude Code subagent dispatch behavior.

Task: per-task-model-selection. Goal: Add per-task implementer model selection driven by a Haiku complexity classifier. Stamp `**Complexity:** low|medium|high` into each task block at /z-plan time (and re-stamp on /z-amend for new/modified tasks). /z-implement-all and /z-implement-next read the stamp and pass `model="sonnet"` or `model="opus"` directly on the implementer Agent(...) call. Retry (cycle ≥ 2) always dispatches model="opus" regardless of stamp. Missing stamp falls back to Sonnet with a logged warning. Replace the prior Z_HARNESS_RETRY_UPGRADE env-var pattern.

Acceptance criteria:
- agents/complexity-classifier.md exists with Haiku frontmatter, declares STATUS:/TIER:/REASON: return shape, no Edit/Write tools.
- /z-plan and skills/z-plan Phase 8 documents the parallel classifier dispatch and the **Complexity:** stamp.
- /z-amend and skills/z-amend full-mode documents re-classification for new/modified tasks and preservation for untouched tasks.
- /z-implement-all and skills mirror documents reading the stamp and passing model= on the implementer Agent call; retry block rewritten with model="opus"; env-var paragraph replaced with deprecation note.
- /z-implement-next and skills mirror: same dispatch logic.
- agents/implementer.md "Inputs from caller" updated to reflect orchestrator-driven model selection.
- README.md Z_HARNESS_RETRY_UPGRADE entry struck through with deprecation note.
- No active uses of Z_HARNESS_RETRY_UPGRADE remain (deprecation pointers are OK).
- The Agent(...) tool actually supports a per-call `model` parameter.

Focus your review on:
1. Internal consistency — do command/skill mirrors say the same thing for /z-implement-all vs /z-implement-next?
2. Cross-document references — does the classifier subagent return contract (STATUS: classified / TIER: low|medium|high / REASON:) match what orchestrators parse?
3. Gap analysis — anywhere a prior code path implicitly depended on Z_HARNESS_RETRY_UPGRADE that was missed? Anywhere the new model param is referenced but control flow doesn't actually use it?
4. Whether the missing-stamp fallback ("default to sonnet, log warning") is robust.
5. Anything in implementer.md prose that contradicts the new orchestrator-driven model selection.
6. Note: the diff also includes a brand-new z-amend command/skill and Phase 1 doc-fetcher restructuring of /z-plan — these are arguably scope creep. Flag if any of it actually contradicts the per-task-model-selection goal.

Key excerpts from the diff:

=== agents/complexity-classifier.md (NEW) ===
---
name: complexity-classifier
description: Reads a single task block (plus optional SPEC.md slice) and returns a complexity tier — `low`, `medium`, or `high`...
tools: Read, Grep, Glob
model: haiku
---

[Tier defs: low maps to sonnet today (same as medium), medium → Sonnet, high → Opus on first attempt]

Return shape:
```
STATUS: classified
TASK: <ID from the task block, e.g. T004>
TIER: low | medium | high
REASON: <one line, ≤120 chars, naming the heuristic that triggered>
```

Heuristic 1: User-authored override. If task block already contains `**Complexity:** low|medium|high`, return that tier verbatim with `REASON: user-authored override`.

=== agents/implementer.md (modified) ===
Frontmatter still has `model: sonnet`.
- Optional: prior-attempt reviewer feedback if retry. On retry the orchestrator dispatches you with `Agent(model="opus")` directly — header says `RETRY v<N>`; effective model is already Opus.
- `**Complexity:** <tier>` line — orchestrator stamps at plan-time and uses to pick model: `low|medium` → Sonnet, `high` → Opus. You don't act on tier yourself.

=== commands/z-implement-all.md step 5 ===
Pick model from `**Complexity:**` stamp:
- `low` or `medium` → `model="sonnet"`
- `high` → `model="opus"`
- Stamp missing: default `model="sonnet"` AND log `missing_complexity_stamp` warning. Do not block; do not JIT-classify.

Retry override. Cycle ≥ 2 force `model="opus"` regardless of stamp.

```
Agent(
  subagent_type="implementer",
  description="Implement <task-id>",
  model="<sonnet|opus per the rules above>",
  prompt="<task-id>\n\n<task block verbatim>..."
)
```

This replaces previous Z_HARNESS_RETRY_UPGRADE=opus env-var pattern. Agent(...) supports per-call `model` override directly.

User-authored override: A user editing `**Complexity:** high` directly hand-picks Opus. The classifier preserves user-authored stamps (returns `REASON: user-authored override`).

Cycle ≥ 2 retry block (later in same command):
```
Agent(
  subagent_type="implementer",
  description="Implement <task-id> v<CYCLE>",
  model="opus",
  prompt="<task-id> RETRY v<CYCLE>\n\n<task block verbatim>..."
)
```

=== commands/z-implement-next.md ===
Same rules; same dispatch block with model="<sonnet|opus per the rules above>".
"This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly."
NOTE: z-implement-next has NO explicit cycle≥2 retry dispatch block written out — the retry rule is stated but no concrete retry Agent() example is given here (unlike z-implement-all which has both first-pass and retry blocks).

=== skills/z-implement-all/SKILL.md and skills/z-implement-next/SKILL.md ===
Mirror commands word-for-word for the model selection rules I've quoted above.

=== commands/z-plan.md & skills/z-plan/SKILL.md Phase 8 ===
"**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task..."
"If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time), the classifier returns `REASON: user-authored override` and you leave the stamp alone."

=== commands/z-amend.md & skills/z-amend/SKILL.md Phase 6 (Full mode, TASKS.md) ===
"**Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte. Log one `task_classified` event per re-classified task."

=== README.md ===
"- ~~`Z_HARNESS_RETRY_UPGRADE`~~ — removed. The implementer model is now picked directly via `Agent(model=...)` based on the task block's `**Complexity:** low|medium|high` stamp (`low|medium` → Sonnet, `high` → Opus). Retries (cycle ≥ 2) always dispatch with `model="opus"`. The complexity stamp is added at plan-time by a Haiku `complexity-classifier` subagent and is user-editable in TASKS.md."

=== Verification grep across final files ===
Only references to Z_HARNESS_RETRY_UPGRADE remaining are deprecation pointers (in the "this replaces…" sentences and the struck-through README entry). No active uses.

Note on Agent model param: Claude Code's Agent/Task tool DOES support a per-call `model` parameter (values like "haiku", "sonnet", "opus"). Verify this matches your own knowledge if you can.

Scrutinize this rigorously. Claude is prone to: over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, silent scope expansion.

Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations (mirror docs should stay in sync)
5. Security concerns
6. Anything else worth flagging — including scope creep (z-amend full file, doc-fetcher Phase 1 rewrite) that may not belong in this task.

**OUTPUT BUDGET — respect strictly:**
- Total response under **8000 characters**.
- Report **blockers and majors only**.
- One finding per bullet. Two sentences max per finding.
- No re-stating code from the diff. No summaries.
- If no blockers or majors, respond exactly: `No blockers or majors found.` (plus optional 1-line note).
