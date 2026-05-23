2026-05-22T05:31:48.439749Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-22T05:31:48.439943Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-22T05:31:48.439961Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.125.0 (research preview)
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR, /Users/zeke/.codex/memories]
reasoning effort: medium
reasoning summaries: none
session id: 019e4e2b-1b5a-74c3-af77-7a8ea54da3a0
--------
user
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

codex
I’ll inspect the actual markdown files rather than relying only on the excerpts, then I’ll focus the review on blocker/major risks against the acceptance criteria.
exec
/bin/zsh -lc 'rg --files .' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
./skills/z-review-all/SKILL.md
./skills/z-init-docs/SKILL.md
./skills/z-do/SKILL.md
./skills/z-implement-next/SKILL.md
./skills/z-implement-all/SKILL.md
./skills/z-debug/SKILL.md
./skills/z-stats/SKILL.md
./skills/z-test/SKILL.md
./skills/z-maintain-docs/SKILL.md
./skills/z-plan-light/SKILL.md
./skills/z-amend/SKILL.md
./skills/z-improve/SKILL.md
./skills/z-plan/SKILL.md
./commands/z-review-all.md
./commands/z-implement-next.md
./commands/z-amend.md
./commands/z-skill-fix.md
./commands/z-stats.md
./commands/z-debug.md
./commands/z-do.md
./commands/z-implement-all.md
./commands/z-improve.md
./commands/z-plan-light.md
./commands/z-plan.md
./commands/z-maintain-docs.md
./commands/z-test.md
./commands/z-init-docs.md
./commands/z-audit.md
./scripts/log-phase.sh
./scripts/log-event.sh
./scripts/version.sh
./scripts/remote-sandbox-sync.sh
./README.md
./plugin.json
./agents/gemini-consultant.md
./agents/implementer.md
./agents/complexity-classifier.md
./agents/codex-reviewer.md
./agents/doc-fetcher.md
./agents/spec-precheck.md
./agents/codex-consultant.md
./agents/remote-runner.md
./agents/doc-updater.md
./agents/auditor.md
./z-harness/metrics.jsonl
./z-harness/archive/20260522T051054Z-per-task-model-selection/events.jsonl
./z-harness/archive/tasks/per-task-model-selection/events.jsonl
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.response.md
./per-task-model-selection/FIX.md
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/phase1-context.md

exec
/bin/zsh -lc "rg -n \"Z_HARNESS_RETRY_UPGRADE|Complexity:|complexity-classifier|Agent\\(|model=|model:\" ." in /Users/zeke/dev/z-harness
 succeeded in 0ms:
./skills/z-review-all/SKILL.md:92:Spawn both in a single message via parallel `Agent()` calls. Each consultant gets the **same inputs**:
./skills/z-review-all/SKILL.md:120:Agent(
./skills/z-review-all/SKILL.md:125:Agent(
./skills/z-review-all/SKILL.md:132:Both consultants are already on `model: haiku` — they just shell out to gemini/codex CLIs. The actual reasoning is done by Gemini and Codex themselves.
./skills/z-implement-next/SKILL.md:47:**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./skills/z-implement-next/SKILL.md:48:- `low` or `medium` → `model="sonnet"`
./skills/z-implement-next/SKILL.md:49:- `high` → `model="opus"`
./skills/z-implement-next/SKILL.md:50:- **Stamp missing**: default to `model="sonnet"` and log a `missing_complexity_stamp` warning event with the task id.
./skills/z-implement-next/SKILL.md:52:**Retry override.** If this dispatch is cycle ≥ 2 (retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The `RETRY v<N>` in-prompt header is the implementer's signal to apply Opus-level care.
./skills/z-implement-next/SKILL.md:55:Agent(
./skills/z-implement-next/SKILL.md:58:  model="<sonnet|opus per the rules above>",
./skills/z-implement-next/SKILL.md:63:This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./skills/z-implement-next/SKILL.md:75:Agent(
./skills/z-improve/SKILL.md:117:Agent(subagent_type="gemini-consultant",
./skills/z-improve/SKILL.md:120:Agent(subagent_type="codex-consultant",
./skills/z-do/SKILL.md:55:Agent(subagent_type="doc-fetcher",
./skills/z-do/SKILL.md:106:Agent(
./skills/z-do/SKILL.md:132:Agent(subagent_type="codex-consultant",
./skills/z-init-docs/SKILL.md:85:Agent(
./commands/z-review-all.md:92:Spawn both in a single message via parallel `Agent()` calls. Each consultant gets the **same inputs**:
./commands/z-review-all.md:120:Agent(
./commands/z-review-all.md:125:Agent(
./commands/z-review-all.md:132:Both consultants are already on `model: haiku` — they just shell out to gemini/codex CLIs. The actual reasoning is done by Gemini and Codex themselves.
./skills/z-test/SKILL.md:109:Agent(
./skills/z-test/SKILL.md:114:Agent(
./agents/gemini-consultant.md:5:model: haiku
./commands/z-implement-next.md:47:**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./commands/z-implement-next.md:48:- `low` or `medium` → `model="sonnet"`
./commands/z-implement-next.md:49:- `high` → `model="opus"`
./commands/z-implement-next.md:50:- **Stamp missing**: default to `model="sonnet"` and log a `missing_complexity_stamp` warning event with the task id.
./commands/z-implement-next.md:52:**Retry override.** If this dispatch is cycle ≥ 2 (retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The `RETRY v<N>` in-prompt header is the implementer's signal to apply Opus-level care.
./commands/z-implement-next.md:55:Agent(
./commands/z-implement-next.md:58:  model="<sonnet|opus per the rules above>",
./commands/z-implement-next.md:63:This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./commands/z-implement-next.md:75:Agent(
./agents/implementer.md:5:model: sonnet
./agents/implementer.md:17:- Optional: **prior-attempt reviewer feedback** if this is a retry. On retry the orchestrator dispatches you with `Agent(model="opus")` directly — your in-prompt header will say `RETRY v<N>` and your effective model is already Opus; apply Opus-level care to the fix.
./agents/implementer.md:18:- **`**Complexity:** <tier>`** line in the task block — the orchestrator stamps this at plan-time (via the `complexity-classifier` Haiku subagent) and uses it to pick your model on the `Agent(...)` call: `low|medium` → Sonnet, `high` → Opus. Users may also hand-author or hand-edit this line as an override. You do not need to act on the tier yourself — the orchestrator has already chosen your model — but if your in-prompt header indicates `high`, treat it as confirmation that the task warrants harder reasoning.
./skills/z-maintain-docs/SKILL.md:44:Agent(
./skills/z-maintain-docs/SKILL.md:55:For each `doc-updater` return from Phase 2, spawn **both** consultants in parallel (single message, multiple `Agent()` calls) to verify the proposed update is accurate:
./skills/z-maintain-docs/SKILL.md:58:Agent(
./skills/z-maintain-docs/SKILL.md:63:Agent(
./skills/z-plan/SKILL.md:99:Agent(
./skills/z-plan/SKILL.md:118:**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./skills/z-plan/SKILL.md:121:Agent(
./skills/z-plan/SKILL.md:123:  model: "haiku",
./skills/z-plan/SKILL.md:129:**When to upgrade Explore to Sonnet:** if the question requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Sonnet. Interpreting > Sonnet. Default > Haiku.
./skills/z-plan/SKILL.md:180:- `Agent(subagent_type="gemini-consultant", ...)`
./skills/z-plan/SKILL.md:181:- `Agent(subagent_type="codex-consultant", ...)`
./skills/z-plan/SKILL.md:243:**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./skills/z-plan/SKILL.md:248:If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./commands/z-amend.md:122:Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./commands/z-amend.md:124:Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./commands/z-amend.md:145:   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./skills/z-implement-all/SKILL.md:47:3. **Parallel dispatch (per phase):** within a batch, run the spec-precheck for all batch tasks in a single message with multiple `Agent()` calls. Same for the implementer phase. Same for the reviewer phase. **Always parallelize independent subagent calls.**
./skills/z-implement-all/SKILL.md:141:Agent(
./skills/z-implement-all/SKILL.md:160:**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./skills/z-implement-all/SKILL.md:161:- `low` or `medium` → `model="sonnet"`
./skills/z-implement-all/SKILL.md:162:- `high` → `model="opus"`
./skills/z-implement-all/SKILL.md:163:- **Stamp missing** (legacy plan, or hand-deleted): default to `model="sonnet"` AND log a `missing_complexity_stamp` warning event with the task id. Do not block; do not JIT-classify.
./skills/z-implement-all/SKILL.md:165:**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this skill) is the implementer's signal to apply Opus-level care to the fix.
./skills/z-implement-all/SKILL.md:168:Agent(
./skills/z-implement-all/SKILL.md:171:  model="<sonnet|opus per the rules above>",
./skills/z-implement-all/SKILL.md:176:This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./skills/z-implement-all/SKILL.md:178:**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./skills/z-implement-all/SKILL.md:183:Agent(
./skills/z-implement-all/SKILL.md:207:Agent(
./skills/z-implement-all/SKILL.md:245:Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
./skills/z-implement-all/SKILL.md:248:Agent(
./skills/z-implement-all/SKILL.md:251:  model="opus",
./skills/z-implement-all/SKILL.md:268:Agent(
./skills/z-implement-all/SKILL.md:366:Most `*_start` / `*_end` events are emitted by the subagents themselves (the orchestrator can't time a subagent from outside, since `Agent()` is an in-process tool call, not a shell process). The relevant subagents — `spec-precheck`, `implementer`, `codex-reviewer` — call `scripts/log-phase.sh start`/`end` at the top and bottom of their procedure. Read those agent files for the exact payload shape.
./skills/z-implement-all/SKILL.md:405:You can't actually "timeout" a subagent — `Agent()` calls are synchronous. But surfacing the wait is useful so the user knows whether to interrupt.
./README.md:107:- ~~`Z_HARNESS_RETRY_UPGRADE`~~ — removed. The implementer model is now picked directly via `Agent(model=...)` based on the task block's `**Complexity:** low|medium|high` stamp (`low|medium` → Sonnet, `high` → Opus). Retries (cycle ≥ 2) always dispatch with `model="opus"`. The complexity stamp is added at plan-time by a Haiku `complexity-classifier` subagent and is user-editable in TASKS.md.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/phase1-context.md:5:Today `/z-implement-all` and `/z-implement-next` dispatch every task to a Sonnet implementer on first attempt. Hard tasks burn a wasted Sonnet cycle (often producing a diff Codex flags with blockers) before retry. The harness already has a `Z_HARNESS_RETRY_UPGRADE=opus` env var and an opt-in `**Complexity:** high` task marker, but [commands/z-implement-all.md:168](../../commands/z-implement-all.md) explicitly notes this is only an *advisory care signal* read by the implementer's prompt — not a real model override. The Agent tool now supports a per-call `model` override; this fix wires that to a Haiku-classifier-stamped `**Complexity:**` tier on each task block.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/phase1-context.md:9:Files affected: `agents/implementer.md` (frontmatter + retry-care prose), `commands/z-plan.md` (Phase 8 emits TASKS.md), `commands/z-amend.md` (full-mode TASKS.md edits), `commands/z-implement-all.md` (line 158 implementer dispatch + retry-bump block), `commands/z-implement-next.md` (single-task variant). `/z-plan-light` Phase 7 runs implementation inline in the orchestrator thread (no implementer subagent), so light mode is **out of scope** — the classifier is irrelevant there. `/z-amend` light-mode also skipped for the same reason. Scope drops from 6 → 5 files. New file: `agents/complexity-classifier.md` (Haiku).
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/phase1-context.md:13:- **Is this a real problem?** Yes. Documented in z-implement-all.md:168 — the current "Z_HARNESS_RETRY_UPGRADE=opus" env var is acknowledged as a stub that does not actually change the model. Hard tasks today must fail Sonnet review once before getting Opus-level care.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/phase1-context.md:14:- **Will the fix solve it?** Yes. The `Agent(...)` tool already has a `model` parameter (verified in tool schema: `"model": {"description": "Optional model override for this agent..."`). Wiring it removes the "this is aspirational" caveat.
./commands/z-skill-fix.md:113:Agent(
./skills/z-plan-light/SKILL.md:58:   Agent(subagent_type="doc-fetcher",
./skills/z-plan-light/SKILL.md:79:Agent(
./skills/z-plan-light/SKILL.md:84:Agent(
./skills/z-plan-light/SKILL.md:188:Agent(
./agents/complexity-classifier.md:2:name: complexity-classifier
./agents/complexity-classifier.md:5:model: haiku
./agents/complexity-classifier.md:24:1. **User-authored override.** If the task block already contains `**Complexity:** low|medium|high`, return that tier verbatim with `REASON: user-authored override`.
./skills/z-amend/SKILL.md:122:Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./skills/z-amend/SKILL.md:124:Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./skills/z-amend/SKILL.md:145:   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./skills/z-debug/SKILL.md:123:Agent(subagent_type="doc-fetcher",
./skills/z-debug/SKILL.md:141:Agent(
./skills/z-debug/SKILL.md:146:Agent(
./per-task-model-selection/FIX.md:9:`/z-implement-all` and `/z-implement-next` dispatch every task to a Sonnet implementer on first attempt. Hard tasks waste a Sonnet cycle before failing Codex review. The existing `Z_HARNESS_RETRY_UPGRADE=opus` env var and `**Complexity:** high` opt-in are documented as advisory care signals only — they do not actually change the model. The `Agent(...)` tool now supports a per-call `model` parameter, so we can right-size implementer model per task.
./per-task-model-selection/FIX.md:13:`agents/implementer.md` declares `model: sonnet` in frontmatter; orchestrator dispatch sites in `commands/z-implement-all.md:158-170` and `commands/z-implement-next.md:55` only set an env var rather than passing `model=` on the `Agent(...)` call. The wire is missing.
./per-task-model-selection/FIX.md:17:1. **New `agents/complexity-classifier.md`** (Haiku subagent). Reads one task block + a SPEC.md slice the caller passes; returns `STATUS: classified\nTIER: low|medium|high\nREASON: <one line>`. No file edits. Self-contained.
./per-task-model-selection/FIX.md:18:2. **`/z-plan` Phase 8**: after writing TASKS.md, dispatch the classifier per task in parallel (single message, multiple Agent calls). Append `**Complexity:** <tier>` to each task block. Log a `task_classified` event per task to `events.jsonl` capturing the tier and rationale.
./per-task-model-selection/FIX.md:19:3. **`/z-amend` full-mode Phase 6**: for tasks added or whose acceptance/files block was materially modified, dispatch the classifier and update/append the `**Complexity:**` line. Preserve existing stamps on untouched tasks. Light mode unaffected — no implementer subagent runs there.
./per-task-model-selection/FIX.md:20:4. **`/z-implement-all` step 5 + `/z-implement-next`**: read `**Complexity:**` from the task block. Pass `model="sonnet"` for `low|medium` and `model="opus"` for `high` on the implementer `Agent(...)` call. If the stamp is missing, default to `model="sonnet"` and log a `missing_complexity_stamp` warning event.
./per-task-model-selection/FIX.md:21:5. **Retry bump**: on cycle ≥ 2 dispatch (after Codex review blockers/majors), always pass `model="opus"` regardless of stamp. Remove the `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern — direct model param replaces it. Keep an in-prompt "this is retry v<N> — apply Opus-level care to the fix" text signal so the implementer's prompt still primes for careful work.
./per-task-model-selection/FIX.md:22:6. **`agents/implementer.md`**: frontmatter stays `model: sonnet` as the fallback default (when no override is passed). Rewrite the "Optional: **prior-attempt reviewer feedback** if this is a retry. If `Z_HARNESS_RETRY_UPGRADE=opus` is set..." prose to reflect that the orchestrator now picks the model directly via `Agent(model=...)`, not via env-var care signal. Keep the `**Complexity:** high` user opt-in language — it still works as a user override that the classifier and orchestrator both respect.
./per-task-model-selection/FIX.md:26:- `/Users/zeke/dev/z-harness/agents/complexity-classifier.md` (new)
./per-task-model-selection/FIX.md:35:- [ ] `agents/complexity-classifier.md` exists with Haiku frontmatter, declares its return shape (`STATUS:`, `TIER:`, `REASON:`), and is read-only (no Edit/Write tools).
./per-task-model-selection/FIX.md:36:- [ ] `/z-plan` Phase 8 documents the parallel-classifier dispatch and the `**Complexity:**` stamp.
./per-task-model-selection/FIX.md:38:- [ ] `/z-implement-all` step 5 documents reading the stamp and passing `model=` on the implementer Agent call; the retry-bump block is rewritten to use `model="opus"` directly; the env-var paragraph is replaced.
./per-task-model-selection/FIX.md:41:- [ ] No `Z_HARNESS_RETRY_UPGRADE` references remain in the harness command/agent files.
./per-task-model-selection/FIX.md:48:- Synthesized call: Option A (plan-time stamping). Retry bump = always Opus (per Codex). Missing-stamp fallback = `medium` (Sonnet) with logged warning. Remove `Z_HARNESS_RETRY_UPGRADE` env var; replace with direct `model=` parameter on `Agent(...)`. Classifier rationale logged to `events.jsonl`, not stamped into TASKS.md.
./commands/z-plan-light.md:58:   Agent(subagent_type="doc-fetcher",
./commands/z-plan-light.md:79:Agent(
./commands/z-plan-light.md:84:Agent(
./commands/z-plan-light.md:188:Agent(
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:11:**Current tooling:** `Agent(...)` now supports per-call `model` override parameter (e.g., `model="sonnet"` or `model="opus"`).
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:22:- During `/z-plan` Phase 8 (TASKS.md generation) and `/z-amend` (full-mode TASKS.md edits), dispatch a Haiku `complexity-classifier` subagent in parallel per task.
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:23:- Append `**Complexity:** low|medium|high` to each task block in TASKS.md.
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:49:- Store classifier result in TASKS.md as `**Complexity:**` stamp (like Option A).
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:57:- **Complexity:** Adds logic to detect "has this task changed since the stamp" — doable via `mtime` on TASKS.md or hash of the task block itself.
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:65:**z-implement-all.md lines 158-170:** Currently sets `Z_HARNESS_RETRY_UPGRADE=opus` env var if task has `**Complexity:** high` or if retry cycle ≥ 2. This is an *advisory signal*, not a model override — implementer reads it in its prompt.
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.prompt.md:67:**Agent() tool:**  Now supports `model="sonnet"` / `model="opus"` per-call override, so we can pass the model directly when dispatching.
./agents/remote-runner.md:5:model: haiku
./commands/z-debug.md:123:Agent(subagent_type="doc-fetcher",
./commands/z-debug.md:141:Agent(
./commands/z-debug.md:146:Agent(
./agents/codex-reviewer.md:5:model: haiku
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.response.md:1:Recommend **Option A: plan-time stamping**, with a narrow mitigation: `/z-amend` should preserve existing `**Complexity:**` stamps for unchanged tasks and classify only new or materially rewritten task blocks.
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.response.md:5:- It is the simplest operational model: `TASKS.md` becomes the source of truth, and implementers just read `low|medium|high`.
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.response.md:8:- It integrates cleanly with the current pattern that already checks `**Complexity:** high`.
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.response.md:16:- Classify only tasks missing `**Complexity:**`.
./z-harness/archive/light-fix-complexity-classifier/transcripts/001-codex-bundled-decisions.response.md:22:Retry interaction: dispatch should compute model from complexity plus retry bump directly, using the new `Agent(..., model=...)` override. For today:
./agents/spec-precheck.md:5:model: haiku
./agents/doc-updater.md:5:model: sonnet
./agents/auditor.md:5:model: sonnet
./commands/z-do.md:55:Agent(subagent_type="doc-fetcher",
./commands/z-do.md:106:Agent(
./commands/z-do.md:132:Agent(subagent_type="codex-consultant",
./agents/doc-fetcher.md:5:model: haiku
./commands/z-test.md:109:Agent(
./commands/z-test.md:114:Agent(
./agents/codex-consultant.md:5:model: haiku
./commands/z-init-docs.md:85:Agent(
./commands/z-plan.md:99:Agent(
./commands/z-plan.md:118:**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./commands/z-plan.md:121:Agent(
./commands/z-plan.md:123:  model: "haiku",
./commands/z-plan.md:129:**When to upgrade Explore to Sonnet:** if the question requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Sonnet. Interpreting > Sonnet. Default > Haiku.
./commands/z-plan.md:180:- `Agent(subagent_type="gemini-consultant", ...)`
./commands/z-plan.md:181:- `Agent(subagent_type="codex-consultant", ...)`
./commands/z-plan.md:243:**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./commands/z-plan.md:248:If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:9:-- `Z_HARNESS_RETRY_UPGRADE` — `opus` to upgrade the implementer model on second retry.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:10:+- ~~`Z_HARNESS_RETRY_UPGRADE`~~ — removed. The implementer model is now picked directly via `Agent(model=...)` based on the task block's `**Complexity:** low|medium|high` stamp (`low|medium` → Sonnet, `high` → Opus). Retries (cycle ≥ 2) always dispatch with `model="opus"`. The complexity stamp is added at plan-time by a Haiku `complexity-classifier` subagent and is user-editable in TASKS.md.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:22:-- Optional: **prior-attempt reviewer feedback** if this is a retry. If `Z_HARNESS_RETRY_UPGRADE=opus` is set, this is a second retry and the orchestrator wants you to apply Opus-level care to the fix.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:23:-- Optional: **`**Complexity:** high`** marker in the task block — user-explicit opt-in for harder reasoning; treat as a signal even if the model running you doesn't change.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:24:+- Optional: **prior-attempt reviewer feedback** if this is a retry. On retry the orchestrator dispatches you with `Agent(model="opus")` directly — your in-prompt header will say `RETRY v<N>` and your effective model is already Opus; apply Opus-level care to the fix.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:25:+- **`**Complexity:** <tier>`** line in the task block — the orchestrator stamps this at plan-time (via the `complexity-classifier` Haiku subagent) and uses it to pick your model on the `Agent(...)` call: `low|medium` → Sonnet, `high` → Opus. Users may also hand-author or hand-edit this line as an override. You do not need to act on the tier yourself — the orchestrator has already chosen your model — but if your in-prompt header indicates `high`, treat it as confirmation that the task warrants harder reasoning.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:37:+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:38:+- `low` or `medium` → `model="sonnet"`
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:39:+- `high` → `model="opus"`
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:40:+- **Stamp missing** (legacy plan, or hand-deleted): default to `model="sonnet"` AND log a `missing_complexity_stamp` warning event with the task id. Do not block; do not JIT-classify.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:42:+**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this command) is the implementer's signal to apply Opus-level care to the fix.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:45: Agent(
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:48:+  model="<sonnet|opus per the rules above>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:53:-**Model-on-retry signal.** If this is the second retry (cycle ≥ 2) after review blockers/majors, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the `Agent()` call so the implementer knows the orchestrator wants Opus-level care for the fix. (The implementer's frontmatter declares `model: sonnet` as default; the env-var is a per-call signal for the agent to read in its prompt construction, not a model override per se. If the harness later supports per-call model override, this maps to that.)
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:54:+This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:56:-**`**Complexity:** high` opt-in.** If the user wrote `**Complexity:** high` in the task block, also set the upgrade signal even on first attempt.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:57:+**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:66:+Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:69: Agent(
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:72:+  model="opus",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:87:+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:88:+- `low` or `medium` → `model="sonnet"`
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:89:+- `high` → `model="opus"`
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:90:+- **Stamp missing**: default to `model="sonnet"` and log a `missing_complexity_stamp` warning event with the task id.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:92:+**Retry override.** If this dispatch is cycle ≥ 2 (retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The `RETRY v<N>` in-prompt header is the implementer's signal to apply Opus-level care.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:95: Agent(
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:98:+  model="<sonnet|opus per the rules above>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:103:-If this is a retry after review failure with `cycle ≥ 2`, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the call (per the auto-upgrade-on-retry policy). Also set the env if the task block has `**Complexity:** high`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:104:+This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:136:+Agent(
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:156:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:159:+Agent(
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:161:+  model: "haiku",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:167:+**When to upgrade Explore to Sonnet:** if the question requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Sonnet. Interpreting > Sonnet. Default > Haiku.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:178:+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:183:+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:196:+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:197:+- `low` or `medium` → `model="sonnet"`
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:198:+- `high` → `model="opus"`
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:199:+- **Stamp missing** (legacy plan, or hand-deleted): default to `model="sonnet"` AND log a `missing_complexity_stamp` warning event with the task id. Do not block; do not JIT-classify.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:201:+**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this skill) is the implementer's signal to apply Opus-level care to the fix.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:204: Agent(
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:207:+  model="<sonnet|opus per the rules above>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:212:-**Model-on-retry signal.** If this is the second retry (cycle ≥ 2) after review blockers/majors, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the `Agent()` call so the implementer knows the orchestrator wants Opus-level care for the fix. (The implementer's frontmatter declares `model: sonnet` as default; the env-var is a per-call signal for the agent to read in its prompt construction, not a model override per se. If the harness later supports per-call model override, this maps to that.)
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:213:+This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:215:-**`**Complexity:** high` opt-in.** If the user wrote `**Complexity:** high` in the task block, also set the upgrade signal even on first attempt.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:216:+**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:225:+Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:228: Agent(
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:231:+  model="opus",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:246:+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:247:+- `low` or `medium` → `model="sonnet"`
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:248:+- `high` → `model="opus"`
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:249:+- **Stamp missing**: default to `model="sonnet"` and log a `missing_complexity_stamp` warning event with the task id.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:251:+**Retry override.** If this dispatch is cycle ≥ 2 (retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The `RETRY v<N>` in-prompt header is the implementer's signal to apply Opus-level care.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:254: Agent(
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:257:+  model="<sonnet|opus per the rules above>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:262:-If this is a retry after review failure with `cycle ≥ 2`, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the call (per the auto-upgrade-on-retry policy). Also set the env if the task block has `**Complexity:** high`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:263:+This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:309:+Agent(
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:330:+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:333:+Agent(
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:335:+  model: "haiku",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:341:+**When to upgrade Explore to Sonnet:** if the question requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Sonnet. Interpreting > Sonnet. Default > Haiku.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:351:+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:356:+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:361:diff --git a/agents/complexity-classifier.md b/agents/complexity-classifier.md
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:365:+++ b/agents/complexity-classifier.md
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:368:+name: complexity-classifier
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:371:+model: haiku
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:390:+1. **User-authored override.** If the task block already contains `**Complexity:** low|medium|high`, return that tier verbatim with `REASON: user-authored override`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:544:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:546:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:567:+   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:741:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:743:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:764:+   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:811:diff --git a/agents/complexity-classifier.md b/agents/complexity-classifier.md
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:815:+++ b/agents/complexity-classifier.md
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:818:+name: complexity-classifier
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:821:+model: haiku
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:840:+1. **User-authored override.** If the task block already contains `**Complexity:** low|medium|high`, return that tier verbatim with `REASON: user-authored override`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:994:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:996:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:1017:+   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:1191:+Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:1193:+Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
./per-task-model-selection/archive/20260522T051054Z-per-task-model-selection/diff.patch:1214:+   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
./commands/z-audit.md:35:   Agent(subagent_type="doc-fetcher",
./commands/z-audit.md:77:Agent(
./commands/z-audit.md:128:Agent(
./commands/z-audit.md:133:Agent(
./commands/z-audit.md:204:Agent(
./commands/z-maintain-docs.md:44:Agent(
./commands/z-maintain-docs.md:55:For each `doc-updater` return from Phase 2, spawn **both** consultants in parallel (single message, multiple `Agent()` calls) to verify the proposed update is accurate:
./commands/z-maintain-docs.md:58:Agent(
./commands/z-maintain-docs.md:63:Agent(
./commands/z-improve.md:117:Agent(subagent_type="gemini-consultant",
./commands/z-improve.md:120:Agent(subagent_type="codex-consultant",
./commands/z-implement-all.md:47:3. **Parallel dispatch (per phase):** within a batch, run the spec-precheck for all batch tasks in a single message with multiple `Agent()` calls. Same for the implementer phase. Same for the reviewer phase. **Always parallelize independent subagent calls.**
./commands/z-implement-all.md:141:Agent(
./commands/z-implement-all.md:160:**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
./commands/z-implement-all.md:161:- `low` or `medium` → `model="sonnet"`
./commands/z-implement-all.md:162:- `high` → `model="opus"`
./commands/z-implement-all.md:163:- **Stamp missing** (legacy plan, or hand-deleted): default to `model="sonnet"` AND log a `missing_complexity_stamp` warning event with the task id. Do not block; do not JIT-classify.
./commands/z-implement-all.md:165:**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this command) is the implementer's signal to apply Opus-level care to the fix.
./commands/z-implement-all.md:168:Agent(
./commands/z-implement-all.md:171:  model="<sonnet|opus per the rules above>",
./commands/z-implement-all.md:176:This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
./commands/z-implement-all.md:178:**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
./commands/z-implement-all.md:183:Agent(
./commands/z-implement-all.md:207:Agent(
./commands/z-implement-all.md:245:Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
./commands/z-implement-all.md:248:Agent(
./commands/z-implement-all.md:251:  model="opus",
./commands/z-implement-all.md:268:Agent(
./commands/z-implement-all.md:366:Most `*_start` / `*_end` events are emitted by the subagents themselves (the orchestrator can't time a subagent from outside, since `Agent()` is an in-process tool call, not a shell process). The relevant subagents — `spec-precheck`, `implementer`, `codex-reviewer` — call `scripts/log-phase.sh start`/`end` at the top and bottom of their procedure. Read those agent files for the exact payload shape.
./commands/z-implement-all.md:405:You can't actually "timeout" a subagent — `Agent()` calls are synchronous. But surfacing the wait is useful so the user knows whether to interrupt.

codex
The grep shows the new paths are present and the active env-var mentions appear gone from command/agent files. I’m reading the exact dispatch and classifier sections now to look for inconsistencies rather than just keyword presence.
exec
/bin/zsh -lc "sed -n '150,270p' commands/z-implement-all.md" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "sed -n '1,140p' agents/complexity-classifier.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
---
name: complexity-classifier
description: Reads a single task block (plus optional SPEC.md slice) and returns a complexity tier — `low`, `medium`, or `high` — that the orchestrator uses to pick which model to dispatch the implementer at. Cheap Haiku call, one per task, stamped once at plan-time (or re-stamped on /z-amend for new/modified tasks).
tools: Read, Grep, Glob
model: haiku
---

You classify **one task block** into one of three complexity tiers. You do not edit files. You return a structured line the orchestrator parses to pick the implementer model.

## Inputs from caller

- **task_block** — the verbatim task block from TASKS.md (title, Files, Depends, Acceptance, plus any optional `**REMOTE_VERIFY:**` / `**DOCS:**` / `**Tests:**` lines).
- **spec_slice_path** (optional, may be empty) — a `$BASE/SPEC.md` path. Read it ONLY if the task block is ambiguous on its own.
- **repo_root** — absolute path; you may grep/read a referenced file briefly if needed to gauge surface area, but keep it light (this is Haiku, not Sonnet).

## Tier definitions

- **`low`** — Mechanical edits with no design judgment: rename, single-line config change, removing dead code, docstring update, trivial scaffolding (1 file, < ~30 lines diff expected, no algorithm involved). Reserved tier: today the orchestrator maps `low → sonnet` (same as `medium`), but stamping `low` correctly lets the harness later route to Haiku without re-classifying.
- **`medium`** — The default. Multi-file edits with conventional patterns, new functions/structs that follow existing scaffolding, standard CRUD, predictable refactors. Most tasks land here. Maps to Sonnet.
- **`high`** — Genuine reasoning required: concurrency, performance-sensitive math, state-machine invariants, novel algorithms, anything touching money / ordering / signal generation, anything where one wrong sign flip is catastrophic, anything spanning >3 files with non-local interactions. Maps to Opus on first attempt.

## Heuristics (apply in order; first match wins)

1. **User-authored override.** If the task block already contains `**Complexity:** low|medium|high`, return that tier verbatim with `REASON: user-authored override`.
2. **Hard signals → `high`:** task mentions concurrency primitives, lock-free, atomics, transactions, migrations, retention policy, signal sign, P&L, order routing, fill-handling, ML training loop, gradient, loss function, cryptographic primitive, custom allocator, or its Acceptance lists >5 criteria.
3. **Soft signals → `high`:** task touches >3 files OR has `**Tests:**` with ≥3 TEST-NNN entries OR the Acceptance section references invariants/properties (not just "function returns X").
4. **Easy signals → `low`:** task touches exactly 1 file AND Acceptance is ≤2 criteria AND the title contains rename/move/delete/typo/comment/docstring/format.
5. **Default → `medium`.**

If you find yourself reading >2 source files to decide, stop — the task is at least `medium`. Default up, not down.

## Return shape (required)

Return a single message with this exact structure:

```
STATUS: classified
TASK: <ID from the task block, e.g. T004>
TIER: low | medium | high
REASON: <one line, ≤120 chars, naming the heuristic that triggered>
```

No prose before or after. The orchestrator parses these four lines.

## Rules

- Do not edit any file. You have no Edit/Write tools.
- Do not call any other subagent.
- Do not run shell commands beyond Read/Grep/Glob.
- If the task block is malformed (no ID, no Files line), still return a tier — pick `medium` and put `REASON: malformed task block, defaulting medium` so the orchestrator can proceed.

 succeeded in 0ms:
- `STATUS: ok` → continue to step 5.
- `STATUS: spec_problem` → halt new task dispatch, push-notify, present the stale references to the user via `AskUserQuestion`. Most common resolution is patching SPEC.md to reflect reality, then re-running the precheck. Log:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" spec_precheck '{"status":"spec_problem","count":<n>}'
```

The precheck is cheap (≤30s) and saves 30-60 minutes per spec-drift incident — three of the last 13 tasks in run `20260517T223141Z-expand-sports-ml` were spec-drift halts that this would have caught up front.

### 5. Spawn implementer (fresh context)

**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
- `low` or `medium` → `model="sonnet"`
- `high` → `model="opus"`
- **Stamp missing** (legacy plan, or hand-deleted): default to `model="sonnet"` AND log a `missing_complexity_stamp` warning event with the task id. Do not block; do not JIT-classify.

**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this command) is the implementer's signal to apply Opus-level care to the fix.

```
Agent(
  subagent_type="implementer",
  description="Implement <task-id>",
  model="<sonnet|opus per the rules above>",
  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
)
```

This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.

**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.

**REMOTE_VERIFY pre-dispatch.** If the task block contains a `**REMOTE_VERIFY:**` line, before parsing the implementer's return, dispatch the `remote-runner` (Haiku) subagent with the verify command. If the remote build fails, treat the implementer return as if it had `STATUS: unable_to_complete` and present the build log excerpt to the user.

```
Agent(
  subagent_type="remote-runner",
  description="Remote verify <task-id>",
  prompt="task_id: <id>\nslug: <Z_HARNESS_SLUG>\nremote_host: zeke-pc\nverify_cmd: <REMOTE_VERIFY line content>\n$BASE: <abs path>"
)
```

Parse the implementer's return per the `STATUS:` block. Branches:

- `STATUS: ok` → go to step 6 (review)
- `STATUS: needs_clarification` → halt queue, push-notify, present the question to the user via `AskUserQuestion`. After answer, update SPEC.md if appropriate, then re-spawn implementer with the resolved info.
- `STATUS: spec_problem` → halt queue, push-notify, escalate to user. Likely needs SPEC patch before any further tasks proceed.
- `STATUS: decision_needed` → halt queue, push-notify, present the decision + options via `AskUserQuestion`. This is the "major design decision must be approved by user" gate. Record the decision in `$BASE/archive/$RUN/decisions-late.md`. After answer, re-spawn implementer.
- `STATUS: unable_to_complete` → flip `[~]` back to `[ ]`, halt queue, push-notify with the reason.

### 6. Capture diff and spawn reviewer (fresh context)

```bash
mkdir -p $BASE/archive/tasks/<task-id>
git diff > $BASE/archive/tasks/<task-id>/diff.patch 2>/dev/null \
  || ls -la <implementer's FILES_CHANGED> > $BASE/archive/tasks/<task-id>/diff.patch
```

```
Agent(
  subagent_type="codex-reviewer",
  description="Codex review <task-id>",
  prompt="task id: <id>\ntask description: <title>\nacceptance criteria: <criteria verbatim from task block>\ndiff.patch path: <abs path>\nchanged files: <abs paths>\nrelated downstream files (paths only; reviewer Reads them itself): <related_files paths from step 4a>\nrelevant_docs (paths — verify the diff didn't break invariants stated in these): <paths from step 4b>\n$BASE: <abs path>  (read SPEC.md yourself for relevant sections)"
)
```

**Skip-rereview on identical diff.** Before spawning the reviewer on cycle ≥ 2, hash both the current and prior diff:

```bash
NEW_HASH="$(shasum -a 256 "$BASE/archive/tasks/<id>/diff.patch" | awk '{print $1}')"
OLD_HASH="$(shasum -a 256 "$BASE/archive/tasks/<id>/diff-v$((CYCLE-1)).patch" | awk '{print $1}')"
```

If `NEW_HASH == OLD_HASH`, the implementer didn't actually change anything (it pushed back on the prior reviewer's findings rather than editing). **Do not spawn the reviewer.** Instead halt the track with reason `no_change_on_retry`, push-notify, and ask the user via `AskUserQuestion` whether to override (accept the unchanged diff) / patch manually / abandon. Saves one full Codex review cycle on stuck tasks.

Parse the reviewer's response. Group findings by severity.

### 7. Handle review outcome

- **No blockers, no majors** → accept; go to step 8 (done).
- **Has blockers or majors** →
  - **First failure**: re-spawn implementer once with the reviewer's findings as `prior-attempt reviewer feedback`. Then re-review.
  - **Second failure**: halt queue. Push-notify. Present diff + reviewer findings to user; await `AskUserQuestion` for "proceed anyway / patch manually / abandon task / re-spec".

#### 7a. Delta-on-retry (mandatory for cycle ≥ 2)

To avoid re-paying full Opus-implementer + Codex-reviewer round trips on retries, both subagents on cycle ≥ 2 see only the **delta** from the prior attempt, not a fresh dump.

Before re-spawning the implementer for retry:

```bash
# stash the prior diff so we can compute a between-attempts delta
mkdir -p $BASE/archive/tasks/<task-id>
cp $BASE/archive/tasks/<task-id>/diff.patch \
   $BASE/archive/tasks/<task-id>/diff-v$((CYCLE-1)).patch
```

Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):

```
Agent(
  subagent_type="implementer",
  description="Implement <task-id> v<CYCLE>",
  model="opus",
  prompt="<task-id> RETRY v<CYCLE>\n\n<task block verbatim — unchanged>\n\nPrior attempt diff (already on disk at $BASE/archive/tasks/<id>/diff-v<CYCLE-1>.patch — READ IT FIRST, then patch ONLY what the reviewer flagged):\n\n=== Reviewer findings to address ===\n<verbatim ≤8K return from codex-reviewer>\n\nDo NOT rewrite from scratch. Apply targeted fixes. Return the same STATUS report shape."
)
```

After implementer returns, capture the new diff and compute the between-attempts delta for the reviewer:

```bash
git diff > $BASE/archive/tasks/<task-id>/diff.patch
diff -u $BASE/archive/tasks/<task-id>/diff-v$((CYCLE-1)).patch \
        $BASE/archive/tasks/<task-id>/diff.patch \
        > $BASE/archive/tasks/<task-id>/delta-v$CYCLE.patch
```

Reviewer prompt on cycle ≥ 2:

```
Agent(
  subagent_type="codex-reviewer",
  description="Codex review <task-id> v<CYCLE>",

exec
/bin/zsh -lc "sed -n '230,255p' commands/z-plan.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
- "Ship as-is — this plan really is that big"
- "Restructure — let me redesign Phase 8"

Sweet spot: each task fits one fresh context window AND produces ~50–500 lines of diff. Too many micro-tasks = orchestration overhead dominates; too few mega-tasks = bad failure isolation.

**Remote-verify tags.** For any task that touches Rust crates or Python scripts intended for the remote host, append a `**REMOTE_VERIFY:** <cargo command>` line to the task block. Example:
```
**REMOTE_VERIFY:** cargo check -p strategies-sports-ml-mispricing
```
The orchestrator dispatches a `remote-runner` (Haiku) to rsync+build in the sandbox; failure halts the task before review.

**Docs-touched flag.** For any task that touches a user-facing surface (CLI flags, public APIs, configs, schemas), append a `**DOCS:** <concept-slug>` line. This is a hint for `/z-maintain-docs`; not a rigid task on its own.

**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" task_classified \
  "$(printf '{"task":"%s","tier":"%s","reason":%s}' "<task-id>" "<tier>" "$(printf '%s' "<reason>" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")"
```
If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).

## Phase 9 — Finalize archive

Copy `z-harness/$Z_HARNESS_SLUG/{SPEC,PLAN,TASKS}.md` into `z-harness/$Z_HARNESS_SLUG/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).

Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
```

exec
/bin/zsh -lc "sed -n '40,100p' commands/z-implement-next.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:

## Phase 2 — Implement

**Discover relevant_docs.** If `docs/llm/INDEX.json` exists, identify concept docs relevant to this task (same logic as `/z-implement-all` step 4b): (a) `**DOCS:** <slug>` lines in task block; (b) `source_file` overlap with the task's `Files:`. Cap at 5 concept paths. Pass as `relevant_docs` below.

Spawn the implementer subagent (fresh context).

**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
- `low` or `medium` → `model="sonnet"`
- `high` → `model="opus"`
- **Stamp missing**: default to `model="sonnet"` and log a `missing_complexity_stamp` warning event with the task id.

**Retry override.** If this dispatch is cycle ≥ 2 (retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The `RETRY v<N>` in-prompt header is the implementer's signal to apply Opus-level care.

```
Agent(
  subagent_type="implementer",
  description="Implement <task-id>",
  model="<sonnet|opus per the rules above>",
  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path to z-harness/<slug>>\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants): <paths>"
)
```

This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.

Implement the task exactly as specified. No scope expansion. If the spec is wrong or ambiguous, **stop and ask the user** rather than improvising. After the answer, **update SPEC.md** to match the resolved decision before continuing — the spec must stay the source of truth.

Obey DRY/KISS/SOLID. No shortcuts unless PLAN.md explicitly approved one for this task.

## Phase 3 — Codex review

1. Capture the diff: `git diff > $BASE/archive/tasks/<task-id>/diff.patch` (if no git, fall back to listing changed file paths).
2. Spawn the reviewer with the diff, not just file contents:

```
Agent(
  subagent_type="codex-reviewer",
  description="Codex scrutiny of task <ID>",
  prompt="task id: <id>\ntask description: <title>\nacceptance criteria: <verbatim from task block>\ndiff.patch path: <abs path>\nchanged files: <abs paths>\nrelevant_docs (paths — verify the diff didn't break invariants stated here): <paths>\n$BASE: <abs path>  (read SPEC.md yourself for relevant sections)"
)
```

Apply findings that hold up. Push back on those that don't and document the pushback.

## Phase 4 — Spec retro

If during implementation you discovered `$BASE/SPEC.md` was wrong, incomplete, or ambiguous — update it now so the next task starts from accurate ground truth. Log the retro: `log-event.sh "tasks/<task-id>" spec_retro '{"summary":"..."}'`.

## Phase 5 — Mark done + notify

1. Flip `[ ]` to `[x]` in `$BASE/TASKS.md`. Add a one-line completion note under the task.
2. Log task end with summary stats.
3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
4. Brief user summary: what changed, what the reviewer flagged, what's next.

Do **not** auto-advance. Wait for the user to invoke `/z-implement-next` again — this forces a fresh context per task.

exec
/bin/zsh -lc "sed -n '1,80p' agents/implementer.md" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "sed -n '1,180p' commands/z-implement-next.md" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "sed -n '1,210p' commands/z-amend.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
---
name: implementer
description: Implements a single task from z-harness/TASKS.md in a fresh context. Invoked by /z-implement-all once per task to keep main orchestrator context lean. Reads only the slice of SPEC.md/PLAN.md it needs, edits files, returns a structured summary.
tools: Bash, Read, Edit, Write, Grep, Glob
model: sonnet
---

You implement **exactly one task** from `z-harness/TASKS.md` and return a structured summary. You are spawned fresh per task — the orchestrator does not want a chatty narrative, it wants the work done and a tight report back.

## Inputs from caller

- **Task ID** (e.g. `T004`)
- **Task block** verbatim from TASKS.md (files, deps, acceptance criteria)
- **`$BASE` path** (e.g. `z-harness/<slug>`) — read SPEC.md / PLAN.md yourself from `$BASE/SPEC.md` and `$BASE/PLAN.md`. The orchestrator no longer extracts slices for you; this keeps the orchestrator's context light. Read only the sections relevant to your task.
- **`relevant_docs`** (paths, may be empty) — list of `docs/llm/<concept>.json` and `docs/human/<concept>.md` files relevant to this task (discovered by the orchestrator via `**DOCS:**` tags and source-file overlap with `docs/llm/INDEX.json`). **Read each LLM-tier JSON first** — they're small (1-3 KB), state invariants, cross-references, gotchas, and "consumed_by" relationships you may not see by just reading the task's own files. The human-tier markdown is supplementary if the JSON is unclear. If your edits invalidate any claim in a relevant doc, flag it in your `ISSUES:` return so `/z-maintain-docs` can refresh that concept.
- **`tests_md_path`** (path, may be empty) — `$BASE/TESTS.md` if `/z-test` was run for this plan. If the task block contains a `**Tests:** TEST-001, TEST-004, ...` line, **read TESTS.md** and grep for each listed `## TEST-NNN` heading. Each TEST-NNN entry specifies an `Invariant:`, a `Failure class:`, a `Target file:`, a `Setup:`, and an `Assertion:`. You must produce actual test code at `Target file:` that implements the entry's `Assertion:` against the production code you're writing in this same task. The test must fail if a code change violates the named invariant / failure class — not just pass on the current implementation. If the target file does not yet exist in a recognized test directory, create it following the repo's existing test conventions (look at neighboring tests for fixture patterns).
- Optional: **prior-attempt reviewer feedback** if this is a retry. On retry the orchestrator dispatches you with `Agent(model="opus")` directly — your in-prompt header will say `RETRY v<N>` and your effective model is already Opus; apply Opus-level care to the fix.
- **`**Complexity:** <tier>`** line in the task block — the orchestrator stamps this at plan-time (via the `complexity-classifier` Haiku subagent) and uses it to pick your model on the `Agent(...)` call: `low|medium` → Sonnet, `high` → Opus. Users may also hand-author or hand-edit this line as an override. You do not need to act on the tier yourself — the orchestrator has already chosen your model — but if your in-prompt header indicates `high`, treat it as confirmation that the task warrants harder reasoning.

## Procedure

0. **Emit an `implement_start` event** before doing anything else, and an `implement_end` event before returning. Use the helper:

```bash
TOKEN="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" start "tasks/<task-id>" implement \
  "$(printf '{"id":"%s","retry":%d}' "<task-id>" "<0 on first try, N on retry>")")"
# ... do the work below ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" end "$TOKEN" \
  "$(printf '{"id":"%s","retry":%d,"status":"%s","files_changed_count":%d}' \
     "<task-id>" "<retry>" "<status>" "$N_CHANGED")"
```

This populates `implement_*` rows in `metrics.jsonl` so post-run analysis can compute implementer wall_ms, retry rate, and files-changed distribution.

1. Read each file in the task's "Files" list (Read tool).
2. Re-read the relevant SPEC.md slice if anything is ambiguous; if still ambiguous, **STOP and return `status: "needs_clarification"`** with the specific question. Do not improvise.
3. **Premise check.** If during reading you realize the task is wrong, infeasible as specified, or would break an invariant in SPEC.md, return `status: "spec_problem"` with the issue. Do not implement around a bad spec.
4. Implement the task per the acceptance criteria. No scope expansion. Obey DRY/KISS/SOLID. No shortcuts unless PLAN.md explicitly approved one.
5. If during implementation you hit an **unforeseen non-obvious decision** (per the same rules `/z-plan` uses — new dep, new public surface, algorithm with materially different tradeoffs, persistence change), STOP and return `status: "decision_needed"` with the decision and ≥2 options. Do not pick one yourself.
6. Run any tests the task explicitly mentions writing (if applicable and runnable locally).
7. Return.

## Common-critique self-check (mandatory before returning STATUS: ok)

Codex reviews keep flagging the same five things across tasks. Run this checklist on your own diff before returning `STATUS: ok`. For each item that applies, **fix it first** — do not leave it for the reviewer:

1. **Broad exception handlers.** Did you add `except Exception` / `except:` / `catch (Throwable)` / `catch (_)` blocks? Replace with the specific exception you expect (`HTTPError`, `FileNotFoundError`, `serde_json::Error`, etc.). If you genuinely need a broad catch, re-raise after logging.
2. **Scope expansion.** Did you edit any file *not* listed in the task's "Files:" block? If yes, revert that change and either (a) confirm it's necessary and add an `ISSUES:` note, or (b) drop it.
3. **Unsolicited validation / error paths.** Did you add input validation, retries, fallbacks, or feature flags not requested in the acceptance criteria? Remove them. The spec is the contract.
4. **New public surface beyond the spec.** Did you export a function, define a public type, or add a CLI flag not in the spec? Remove or downgrade to private/internal. The spec's "Surface:" section is authoritative.
5. **Stale docstrings / comments.** Did your edits invalidate any nearby docstring, comment, or README claim? Update or delete the stale claim.
6. **TESTS.md coverage.** If your task block has a `**Tests:**` line, did you produce a test for *every* listed TEST-NNN entry, at the specified `Target file:`, with an assertion that actually exercises the `Failure class:` named in the entry? A test that compiles and passes but doesn't fail on a deliberate violation of the invariant is a trivial test — strengthen it before returning `STATUS: ok`.

If you applied a fix from this checklist, mention it in `SUMMARY:`. If you intentionally kept something the checklist flags (e.g. broad catch is genuinely correct for this code), justify it in an `ISSUES:` note so the reviewer doesn't waste a cycle flagging it.

## Return shape (required)

Return a single message with this exact structure so the orchestrator can parse it:

```
STATUS: ok | needs_clarification | spec_problem | decision_needed | unable_to_complete
TASK: <ID>
FILES_CHANGED:
  - <abs path>
  - <abs path>
SUMMARY:
  <2-4 sentences on what was done>
ACCEPTANCE_SELF_CHECK:
  - <criterion 1>: <pass|fail|untested + why>
  - <criterion 2>: ...
TESTS_IMPLEMENTED (omit if task has no **Tests:** line):
  - TEST-NNN at <abs target file path>: <one line on what the assertion checks>
ISSUES (if any non-ok status):
  <verbatim question / decision / problem statement for the orchestrator to escalate>
```

## Rules

- Do not edit `z-harness/TASKS.md` — that's the orchestrator's job.
- Do not spawn other subagents.

 succeeded in 0ms:
---
description: Implement the next pending task from z-harness/TASKS.md, then have Codex scrutinize the diff.
---

You are running the **z-harness `/z-implement-next`** pipeline.

Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`).

## Phase 0 — Discover plan slug

Multiple plans may coexist under `z-harness/<slug>/`. Determine which one to operate on:

1. Enumerate candidates:
   - List immediate subdirs of `z-harness/` that contain a `TASKS.md`.
   - Also check for legacy flat layout: a `TASKS.md` directly under `z-harness/` (no slug).
2. Choose:
   - **One candidate** → use it. If slug-namespaced, `export Z_HARNESS_SLUG=<slug>`. If legacy flat, leave `Z_HARNESS_SLUG` unset.
   - **Multiple candidates** → `AskUserQuestion` with each slug as an option. Set `Z_HARNESS_SLUG` to the chosen one.
   - **Zero candidates** → tell the user there's no plan; suggest `/z-plan`. Stop.
3. From here on, **`BASE`** refers to `z-harness/$Z_HARNESS_SLUG` (or `z-harness` if legacy). Paths below use `$BASE`.

## Phase 1 — Load context

1. Read `$BASE/TASKS.md`. Find the first task with status `[ ]`.
2. **Do NOT pre-extract SPEC/PLAN slices in main thread.** Pass `$BASE` to the implementer; the implementer subagent reads `$BASE/SPEC.md` and `$BASE/PLAN.md` itself with its Read tool. Saves main-thread context.
3. (Skip — implementer reads the files it touches.)
4. Create task archive dir: `mkdir -p $BASE/archive/tasks/<task-id>`
5. **Version stamp + task_start:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["id"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<task-id>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_start "$START_PAYLOAD"
   ```

If TASKS.md is missing or has no pending tasks, tell the user and stop.

## Phase 2 — Implement

**Discover relevant_docs.** If `docs/llm/INDEX.json` exists, identify concept docs relevant to this task (same logic as `/z-implement-all` step 4b): (a) `**DOCS:** <slug>` lines in task block; (b) `source_file` overlap with the task's `Files:`. Cap at 5 concept paths. Pass as `relevant_docs` below.

Spawn the implementer subagent (fresh context).

**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
- `low` or `medium` → `model="sonnet"`
- `high` → `model="opus"`
- **Stamp missing**: default to `model="sonnet"` and log a `missing_complexity_stamp` warning event with the task id.

**Retry override.** If this dispatch is cycle ≥ 2 (retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The `RETRY v<N>` in-prompt header is the implementer's signal to apply Opus-level care.

```
Agent(
  subagent_type="implementer",
  description="Implement <task-id>",
  model="<sonnet|opus per the rules above>",
  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path to z-harness/<slug>>\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants): <paths>"
)
```

This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.

Implement the task exactly as specified. No scope expansion. If the spec is wrong or ambiguous, **stop and ask the user** rather than improvising. After the answer, **update SPEC.md** to match the resolved decision before continuing — the spec must stay the source of truth.

Obey DRY/KISS/SOLID. No shortcuts unless PLAN.md explicitly approved one for this task.

## Phase 3 — Codex review

1. Capture the diff: `git diff > $BASE/archive/tasks/<task-id>/diff.patch` (if no git, fall back to listing changed file paths).
2. Spawn the reviewer with the diff, not just file contents:

```
Agent(
  subagent_type="codex-reviewer",
  description="Codex scrutiny of task <ID>",
  prompt="task id: <id>\ntask description: <title>\nacceptance criteria: <verbatim from task block>\ndiff.patch path: <abs path>\nchanged files: <abs paths>\nrelevant_docs (paths — verify the diff didn't break invariants stated here): <paths>\n$BASE: <abs path>  (read SPEC.md yourself for relevant sections)"
)
```

Apply findings that hold up. Push back on those that don't and document the pushback.

## Phase 4 — Spec retro

If during implementation you discovered `$BASE/SPEC.md` was wrong, incomplete, or ambiguous — update it now so the next task starts from accurate ground truth. Log the retro: `log-event.sh "tasks/<task-id>" spec_retro '{"summary":"..."}'`.

## Phase 5 — Mark done + notify

1. Flip `[ ]` to `[x]` in `$BASE/TASKS.md`. Add a one-line completion note under the task.
2. Log task end with summary stats.
3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
4. Brief user summary: what changed, what the reviewer flagged, what's next.

Do **not** auto-advance. Wait for the user to invoke `/z-implement-next` again — this forces a fresh context per task.

 succeeded in 0ms:
---
description: Amend an existing z-harness plan (SPEC/PLAN/TASKS) or light-plan (FIX.md) so a change is propagated consistently across all artifacts. Preserves completed task state; adds/modifies/removes tasks as needed; optionally cross-consults if the amendment is non-obvious.
argument-hint: <what to change about the plan>
---

You are running the **z-harness `/z-amend`** pipeline.

Task (from `$ARGUMENTS`):

$ARGUMENTS

**If the task above is empty** — use `AskUserQuestion` to ask "What amendment should I make to the plan?" before proceeding. Do not invent.

This command modifies an **already-produced** planning artifact set. It does NOT do exploration / consult-everywhere / full premise check — that's `/z-plan`. It does the surgical work of changing one or more decisions / scope items and making sure every downstream artifact (SPEC.md, PLAN.md, TASKS.md, or FIX.md) reflects the change consistently.

## Phase 0 — Discover plan slug

Multiple plans may coexist under `z-harness/<slug>/`. Determine which one to amend:

1. Enumerate candidates: immediate subdirs of `z-harness/` that contain **any** of `SPEC.md`, `PLAN.md`, `TASKS.md`, or `FIX.md`. Also check for legacy flat layout.
2. Choose:
   - **One candidate** → use it. `export Z_HARNESS_SLUG=<slug>` (or leave unset for legacy).
   - **Multiple candidates** → `AskUserQuestion` with each slug as an option (annotate each with mode: `full` if SPEC.md exists, `light` if only FIX.md). Set `Z_HARNESS_SLUG` to chosen.
   - **Zero candidates** → tell the user there's no plan to amend; suggest `/z-plan` or `/z-plan-light`. Stop.
3. From here on, **`$BASE`** refers to `z-harness/$Z_HARNESS_SLUG` (or `z-harness` if legacy).
4. Detect **mode**:
   - `full` if `$BASE/SPEC.md` exists.
   - `light` if only `$BASE/FIX.md` exists.

## Phase 1 — Setup + telemetry

1. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-amend-<slug>`
2. `mkdir -p $BASE/archive/$RUN/transcripts`
3. **Version stamp + log:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["amendment"] = sys.argv[2]; v["mode"] = sys.argv[3]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>" "<full|light>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" amend_run_start "$START_PAYLOAD"
   ```
4. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).

## Phase 2 — Read the current plan

Read every artifact that exists for this slug:

- **full mode:** `$BASE/SPEC.md`, `$BASE/PLAN.md`, `$BASE/TASKS.md`
- **light mode:** `$BASE/FIX.md`

For **full mode**, also snapshot completed task state. Run:
```bash
grep -E '^\- \[x\] T[0-9]+' $BASE/TASKS.md > $BASE/archive/$RUN/completed-tasks.txt || true
```
This is the source of truth for "what must NOT change ID or get deleted under our feet." If the amendment requires changing a task that's already `[x]`, you must surface that to the user in Phase 4 — completed work cannot be silently retracted.

## Phase 3 — Impact analysis

Articulate, in plain prose, what the amendment changes. Write `$BASE/archive/$RUN/amendment.md`:

```markdown
# Amendment: <one-line summary>

**Run:** <RUN>
**Mode:** <full|light>
**Requested change:** <verbatim $ARGUMENTS>

## What this affects

### SPEC.md   (full mode only)
- <bullet per section that changes; "no change" if none>

### PLAN.md   (full mode only)
- <decisions added/changed/removed; phases reordered; non-goals added/dropped>

### TASKS.md  (full mode only)
- **New tasks:** T0NN, T0NN+1, ... (next IDs after current max)
- **Modified tasks:** T0NN (status `[ ]` → still `[ ]`, but acceptance/files/deps changed)
- **Removed tasks:** T0NN (only if status `[ ]`; never remove `[x]`)
- **Touched-but-completed tasks:** T0NN (status `[x]` — flag for user decision)

### FIX.md    (light mode only)
- <which sections change: Problem / Root cause / Approach / Files / Acceptance>

## Risk
- Does this change cross any auto-bail threshold (new external dep, public API change, schema change, cross-module)? If yes → flag for consult in Phase 5.
```

**ID-allocation rule:** new tasks always take fresh IDs (max existing + 1, ...). Never reuse a deleted task's ID.

**Completed-task rule:** if a `[x]` task's behavior is contradicted by the amendment, do NOT edit it in place. Instead, add a new `[ ]` task whose description explicitly says "supersedes T0NN: <reason>". The user sees both in the archive trail.

## Phase 4 — User gate

Show `amendment.md` to the user via `AskUserQuestion`:

- **Approve as drafted** → proceed to Phase 5
- **Revise** (free-text) → loop back to Phase 3 with their tweak
- **Abandon** → log `amend_run_end` with `status: abandoned`; exit

If `Touched-but-completed tasks` is non-empty, ask a **separate explicit** `AskUserQuestion` for each:
- "Add superseding task (recommended)"
- "Re-open T0NN (flip `[x]` → `[ ]`) — work needs to be redone"
- "Leave T0NN alone — amendment doesn't actually contradict it"

Block until answered. Send a `PushNotification` if policy ≠ `off`.

## Phase 5 — Optional cross-LLM consult (only if non-obvious)

If `amendment.md`'s Risk section flagged any of these triggers, run a **bundled** consult:

- New external dependency
- Public API / wire format / schema change
- Cross-module impact in full mode
- Algorithm swap with materially different Big-O / memory
- Persistence change (migration, retention, indexes)

Spawn both in parallel:
```
Agent(subagent_type="gemini-consultant", description="Amend consult (Gemini) for <slug>",
      prompt="MODE: amend\n\nExisting plan: <inline brief — 2-3 paragraphs from SPEC/PLAN summary>\nAmendment: <amendment.md body>\nKey concern: <the risk trigger>\n\nAsk: is the amendment sound? what's likely to break? what did I miss?")
Agent(subagent_type="codex-consultant", description="Amend consult (Codex) for <slug>",
      prompt="<same body>")
```

When both return: apply **one reason it might be wrong** to each recommendation. Synthesize. Update `amendment.md` with a `## Consult outcome` section.

If neither consult trigger fires, skip this phase entirely — the user already approved in Phase 4.

## Phase 6 — Propagate edits

Now apply the amendment to the actual artifacts. Use `Edit` (not `Write`) so diffs stay surgical and reviewable.

### Full mode
1. **SPEC.md** — update only the affected sections. Preserve unrelated content byte-for-byte.
2. **PLAN.md** — update Decisions / Non-goals / Phases sections as listed in `amendment.md`. If a decision is reversed, add a `## Amendments` section at the bottom recording: date, what changed, why (one line each). This gives the archive trail.
3. **TASKS.md**:
   - Append new tasks with fresh IDs in the appropriate phase block.
   - Edit modified `[ ]` tasks in place.
   - Strike-through removed `[ ]` tasks: change `- [ ] T0NN` → `- [~] T0NN ~~<title>~~ (removed in <RUN>)`. Keep them visible — `/z-implement-next` skips `[~]`.
   - For superseded `[x]` tasks: leave them `[x]` and add the new superseding `[ ]` task whose title begins `Supersedes T0NN: ...`.
   - Preserve every `[x]` line untouched unless the user explicitly chose "re-open" in Phase 4.
   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.

### Light mode
1. **FIX.md** — update the affected sections (Problem / Root cause / Approach / Files / Acceptance / Cross-LLM consensus). Add an `## Amendments` section at the bottom: date, what changed, why.

### Both modes
After every file edit, run:
```bash
diff -u <(git show HEAD:$BASE/<file> 2>/dev/null || echo) $BASE/<file> > $BASE/archive/$RUN/<file>.diff
```
(If not under git, snapshot the pre-edit content into `$BASE/archive/$RUN/before/<file>` before editing — Read first, copy via Write.)

## Phase 7 — Validate consistency

Run a self-check. Read each amended file fresh and verify:

- Every task referenced in PLAN.md exists in TASKS.md (and vice versa for non-implicit refs).
- Every file path in TASKS.md "files touched" appears in SPEC.md.
- No `[x]` task was changed without an explicit user-approved supersede.
- No duplicate task IDs.
- For light mode: every file in FIX.md "Files to change" exists or has a clear creation directive.

If any check fails, do **not** silently fix — surface to user via `AskUserQuestion` ("inconsistency found: <X>. Fix automatically / revise / abort").

## Phase 8 — Finalize

1. Log run end:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" amend_run_end \
     "$(printf '{"status":"applied","mode":"%s","tasks_added":%d,"tasks_modified":%d,"tasks_removed":%d,"tasks_superseded":%d,"consulted":%s}' \
        "$MODE" "$N_ADDED" "$N_MOD" "$N_REM" "$N_SUP" "$CONSULTED")"
   ```
2. Push-notify (if policy ≠ `off`): "Amendment applied to `<slug>`. <N> tasks added, <M> modified, <K> removed, <S> superseded."
3. Brief summary to user (3-5 sentences): what changed, what's next.
4. Recommend next step:
   - **full mode with new/modified `[ ]` tasks** → `/z-implement-next` or `/z-implement-all`
   - **light mode** → `/z-plan-light` won't re-run; if the amendment is large enough to warrant re-implementation, suggest the user explicitly trigger that.

## Hard rules

- **Never delete or silently mutate a `[x]` task.** Supersede instead.
- **Never reuse a task ID.** New tasks always get fresh IDs.
- **Never rewrite an artifact wholesale with `Write`** when surgical `Edit` will do. Preserve byte-for-byte content outside the amendment scope.
- **Never skip Phase 4 (user gate).** The user always sees the impact analysis before edits land.
- **Cross-LLM consult only when triggered** — amendments are surgical; full consult is overkill for "rename this field".
- **If the amendment grows past ~30% of the plan** (e.g. >5 new tasks, or the core premise of SPEC.md changes), STOP and recommend `/z-plan` from scratch instead — at that point you're not amending, you're replanning.
- **No emojis** anywhere in artifacts.

exec
/bin/zsh -lc "diff -u commands/z-implement-next.md skills/z-implement-next/SKILL.md | sed -n '1,220p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
--- commands/z-implement-next.md	2026-05-21 22:25:18
+++ skills/z-implement-next/SKILL.md	2026-05-21 22:27:00
@@ -1,7 +1,7 @@
 ---
+name: z-implement-next
 description: Implement the next pending task from z-harness/TASKS.md, then have Codex scrutinize the diff.
 ---
-
 You are running the **z-harness `/z-implement-next`** pipeline.
 
 Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`).

exec
/bin/zsh -lc "nl -ba commands/z-implement-next.md | sed -n '40,115p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
    40	
    41	## Phase 2 — Implement
    42	
    43	**Discover relevant_docs.** If `docs/llm/INDEX.json` exists, identify concept docs relevant to this task (same logic as `/z-implement-all` step 4b): (a) `**DOCS:** <slug>` lines in task block; (b) `source_file` overlap with the task's `Files:`. Cap at 5 concept paths. Pass as `relevant_docs` below.
    44	
    45	Spawn the implementer subagent (fresh context).
    46	
    47	**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
    48	- `low` or `medium` → `model="sonnet"`
    49	- `high` → `model="opus"`
    50	- **Stamp missing**: default to `model="sonnet"` and log a `missing_complexity_stamp` warning event with the task id.
    51	
    52	**Retry override.** If this dispatch is cycle ≥ 2 (retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The `RETRY v<N>` in-prompt header is the implementer's signal to apply Opus-level care.
    53	
    54	```
    55	Agent(
    56	  subagent_type="implementer",
    57	  description="Implement <task-id>",
    58	  model="<sonnet|opus per the rules above>",
    59	  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path to z-harness/<slug>>\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants): <paths>"
    60	)
    61	```
    62	
    63	This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
    64	
    65	Implement the task exactly as specified. No scope expansion. If the spec is wrong or ambiguous, **stop and ask the user** rather than improvising. After the answer, **update SPEC.md** to match the resolved decision before continuing — the spec must stay the source of truth.
    66	
    67	Obey DRY/KISS/SOLID. No shortcuts unless PLAN.md explicitly approved one for this task.
    68	
    69	## Phase 3 — Codex review
    70	
    71	1. Capture the diff: `git diff > $BASE/archive/tasks/<task-id>/diff.patch` (if no git, fall back to listing changed file paths).
    72	2. Spawn the reviewer with the diff, not just file contents:
    73	
    74	```
    75	Agent(
    76	  subagent_type="codex-reviewer",
    77	  description="Codex scrutiny of task <ID>",
    78	  prompt="task id: <id>\ntask description: <title>\nacceptance criteria: <verbatim from task block>\ndiff.patch path: <abs path>\nchanged files: <abs paths>\nrelevant_docs (paths — verify the diff didn't break invariants stated here): <paths>\n$BASE: <abs path>  (read SPEC.md yourself for relevant sections)"
    79	)
    80	```
    81	
    82	Apply findings that hold up. Push back on those that don't and document the pushback.
    83	
    84	## Phase 4 — Spec retro
    85	
    86	If during implementation you discovered `$BASE/SPEC.md` was wrong, incomplete, or ambiguous — update it now so the next task starts from accurate ground truth. Log the retro: `log-event.sh "tasks/<task-id>" spec_retro '{"summary":"..."}'`.
    87	
    88	## Phase 5 — Mark done + notify
    89	
    90	1. Flip `[ ]` to `[x]` in `$BASE/TASKS.md`. Add a one-line completion note under the task.
    91	2. Log task end with summary stats.
    92	3. If notification policy ≠ `off`: send `PushNotification` — "Task <ID> complete. <N> remaining. Run /z-implement-next to continue."
    93	4. Brief user summary: what changed, what the reviewer flagged, what's next.
    94	
    95	Do **not** auto-advance. Wait for the user to invoke `/z-implement-next` again — this forces a fresh context per task.

exec
/bin/zsh -lc "nl -ba commands/z-amend.md | sed -n '136,152p'" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "nl -ba agents/implementer.md | sed -n '14,22p'" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "nl -ba skills/z-amend/SKILL.md | sed -n '136,152p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
    14	- **`$BASE` path** (e.g. `z-harness/<slug>`) — read SPEC.md / PLAN.md yourself from `$BASE/SPEC.md` and `$BASE/PLAN.md`. The orchestrator no longer extracts slices for you; this keeps the orchestrator's context light. Read only the sections relevant to your task.
    15	- **`relevant_docs`** (paths, may be empty) — list of `docs/llm/<concept>.json` and `docs/human/<concept>.md` files relevant to this task (discovered by the orchestrator via `**DOCS:**` tags and source-file overlap with `docs/llm/INDEX.json`). **Read each LLM-tier JSON first** — they're small (1-3 KB), state invariants, cross-references, gotchas, and "consumed_by" relationships you may not see by just reading the task's own files. The human-tier markdown is supplementary if the JSON is unclear. If your edits invalidate any claim in a relevant doc, flag it in your `ISSUES:` return so `/z-maintain-docs` can refresh that concept.
    16	- **`tests_md_path`** (path, may be empty) — `$BASE/TESTS.md` if `/z-test` was run for this plan. If the task block contains a `**Tests:** TEST-001, TEST-004, ...` line, **read TESTS.md** and grep for each listed `## TEST-NNN` heading. Each TEST-NNN entry specifies an `Invariant:`, a `Failure class:`, a `Target file:`, a `Setup:`, and an `Assertion:`. You must produce actual test code at `Target file:` that implements the entry's `Assertion:` against the production code you're writing in this same task. The test must fail if a code change violates the named invariant / failure class — not just pass on the current implementation. If the target file does not yet exist in a recognized test directory, create it following the repo's existing test conventions (look at neighboring tests for fixture patterns).
    17	- Optional: **prior-attempt reviewer feedback** if this is a retry. On retry the orchestrator dispatches you with `Agent(model="opus")` directly — your in-prompt header will say `RETRY v<N>` and your effective model is already Opus; apply Opus-level care to the fix.
    18	- **`**Complexity:** <tier>`** line in the task block — the orchestrator stamps this at plan-time (via the `complexity-classifier` Haiku subagent) and uses it to pick your model on the `Agent(...)` call: `low|medium` → Sonnet, `high` → Opus. Users may also hand-author or hand-edit this line as an override. You do not need to act on the tier yourself — the orchestrator has already chosen your model — but if your in-prompt header indicates `high`, treat it as confirmation that the task warrants harder reasoning.
    19	
    20	## Procedure
    21	
    22	0. **Emit an `implement_start` event** before doing anything else, and an `implement_end` event before returning. Use the helper:

 succeeded in 0ms:
   136	### Full mode
   137	1. **SPEC.md** — update only the affected sections. Preserve unrelated content byte-for-byte.
   138	2. **PLAN.md** — update Decisions / Non-goals / Phases sections as listed in `amendment.md`. If a decision is reversed, add a `## Amendments` section at the bottom recording: date, what changed, why (one line each). This gives the archive trail.
   139	3. **TASKS.md**:
   140	   - Append new tasks with fresh IDs in the appropriate phase block.
   141	   - Edit modified `[ ]` tasks in place.
   142	   - Strike-through removed `[ ]` tasks: change `- [ ] T0NN` → `- [~] T0NN ~~<title>~~ (removed in <RUN>)`. Keep them visible — `/z-implement-next` skips `[~]`.
   143	   - For superseded `[x]` tasks: leave them `[x]` and add the new superseding `[ ]` task whose title begins `Supersedes T0NN: ...`.
   144	   - Preserve every `[x]` line untouched unless the user explicitly chose "re-open" in Phase 4.
   145	   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
   146	
   147	### Light mode
   148	1. **FIX.md** — update the affected sections (Problem / Root cause / Approach / Files / Acceptance / Cross-LLM consensus). Add an `## Amendments` section at the bottom: date, what changed, why.
   149	
   150	### Both modes
   151	After every file edit, run:
   152	```bash

 succeeded in 0ms:
   136	### Full mode
   137	1. **SPEC.md** — update only the affected sections. Preserve unrelated content byte-for-byte.
   138	2. **PLAN.md** — update Decisions / Non-goals / Phases sections as listed in `amendment.md`. If a decision is reversed, add a `## Amendments` section at the bottom recording: date, what changed, why (one line each). This gives the archive trail.
   139	3. **TASKS.md**:
   140	   - Append new tasks with fresh IDs in the appropriate phase block.
   141	   - Edit modified `[ ]` tasks in place.
   142	   - Strike-through removed `[ ]` tasks: change `- [ ] T0NN` → `- [~] T0NN ~~<title>~~ (removed in <RUN>)`. Keep them visible — `/z-implement-next` skips `[~]`.
   143	   - For superseded `[x]` tasks: leave them `[x]` and add the new superseding `[ ]` task whose title begins `Supersedes T0NN: ...`.
   144	   - Preserve every `[x]` line untouched unless the user explicitly chose "re-open" in Phase 4.
   145	   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose Files / Acceptance / `**Tests:**` lines materially changed in this amendment. Dispatch the `complexity-classifier` (Haiku) subagent in parallel for the affected tasks only; append/update the `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
   146	
   147	### Light mode
   148	1. **FIX.md** — update the affected sections (Problem / Root cause / Approach / Files / Acceptance / Cross-LLM consensus). Add an `## Amendments` section at the bottom: date, what changed, why.
   149	
   150	### Both modes
   151	After every file edit, run:
   152	```bash

exec
/bin/zsh -lc "diff -u commands/z-implement-all.md skills/z-implement-all/SKILL.md | sed -n '1,160p'" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "diff -u commands/z-plan.md skills/z-plan/SKILL.md | sed -n '1,180p'" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "diff -u commands/z-amend.md skills/z-amend/SKILL.md | sed -n '1,120p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
--- commands/z-implement-all.md	2026-05-21 22:25:03
+++ skills/z-implement-all/SKILL.md	2026-05-21 22:26:46
@@ -1,7 +1,7 @@
 ---
+name: z-implement-all
 description: Orchestrate implementation of ALL pending tasks in z-harness/TASKS.md, spawning a fresh implementer subagent per task and a codex-reviewer per task. Halts on blockers, retries once on review failure, push-notifies user on every gate.
 ---
-
 You are the **z-harness `/z-implement-all`** orchestrator. Your job is to drive the task queue to completion without losing the per-task fresh-context guarantee. You do not implement code yourself — you delegate each task to a fresh `implementer` subagent and each review to a fresh `codex-reviewer` subagent.
 
 Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`).
@@ -162,7 +162,7 @@
 - `high` → `model="opus"`
 - **Stamp missing** (legacy plan, or hand-deleted): default to `model="sonnet"` AND log a `missing_complexity_stamp` warning event with the task id. Do not block; do not JIT-classify.
 
-**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this command) is the implementer's signal to apply Opus-level care to the fix.
+**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this skill) is the implementer's signal to apply Opus-level care to the fix.
 
 ```
 Agent(

 succeeded in 0ms:
 succeeded in 0ms:
exec
/bin/zsh -lc "nl -ba agents/complexity-classifier.md | sed -n '20,34p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
    20	- **`high`** — Genuine reasoning required: concurrency, performance-sensitive math, state-machine invariants, novel algorithms, anything touching money / ordering / signal generation, anything where one wrong sign flip is catastrophic, anything spanning >3 files with non-local interactions. Maps to Opus on first attempt.
    21	
    22	## Heuristics (apply in order; first match wins)
    23	
    24	1. **User-authored override.** If the task block already contains `**Complexity:** low|medium|high`, return that tier verbatim with `REASON: user-authored override`.
    25	2. **Hard signals → `high`:** task mentions concurrency primitives, lock-free, atomics, transactions, migrations, retention policy, signal sign, P&L, order routing, fill-handling, ML training loop, gradient, loss function, cryptographic primitive, custom allocator, or its Acceptance lists >5 criteria.
    26	3. **Soft signals → `high`:** task touches >3 files OR has `**Tests:**` with ≥3 TEST-NNN entries OR the Acceptance section references invariants/properties (not just "function returns X").
    27	4. **Easy signals → `low`:** task touches exactly 1 file AND Acceptance is ≤2 criteria AND the title contains rename/move/delete/typo/comment/docstring/format.
    28	5. **Default → `medium`.**
    29	
    30	If you find yourself reading >2 source files to decide, stop — the task is at least `medium`. Default up, not down.
    31	
    32	## Return shape (required)
    33	
    34	Return a single message with this exact structure:

codex
- **Major:** `/z-amend` reclassification is effectively disabled for existing stamped tasks. [agents/complexity-classifier.md](/Users/zeke/dev/z-harness/agents/complexity-classifier.md:24) treats any existing `**Complexity:**` as a user override, while [commands/z-amend.md](/Users/zeke/dev/z-harness/commands/z-amend.md:145) sends modified task blocks for reclassification, so previously auto-stamped modified tasks will keep stale tiers unless the old stamp is stripped or the classifier gets explicit “ignore existing auto stamp” context.

- **Major:** `/z-amend` narrows “modified tasks” to only Files / Acceptance / `**Tests:**` changes. [commands/z-amend.md](/Users/zeke/dev/z-harness/commands/z-amend.md:145) and [skills/z-amend/SKILL.md](/Users/zeke/dev/z-harness/skills/z-amend/SKILL.md:145) miss title, dependency, `REMOTE_VERIFY`, and `DOCS` changes, any of which can materially change classification and violates the stated “new/modified tasks” re-stamp requirement.

- **Major:** `/z-implement-next` states the retry override but has no retry dispatch path that can actually use it. [commands/z-implement-next.md](/Users/zeke/dev/z-harness/commands/z-implement-next.md:52) says cycle ≥ 2 forces Opus, but after review it only says to apply findings directly and then mark done, with no second implementer `Agent(..., model="opus")` call; the skill mirror has the same gap.

- **Major:** The missing-stamp fallback says to log `missing_complexity_stamp`, but the command docs do not define the concrete `log-event.sh` call, payload shape, or warning namespace. [commands/z-implement-next.md](/Users/zeke/dev/z-harness/commands/z-implement-next.md:50) is especially under-specified compared with other logging steps, so the “default to Sonnet, log warning” behavior is likely to be implemented inconsistently or skipped.
2026-05-22T05:33:11.669109Z ERROR codex_core::session: failed to record rollout items: thread 019e4e2b-1b5a-74c3-af77-7a8ea54da3a0 not found
tokens used
77,003
- **Major:** `/z-amend` reclassification is effectively disabled for existing stamped tasks. [agents/complexity-classifier.md](/Users/zeke/dev/z-harness/agents/complexity-classifier.md:24) treats any existing `**Complexity:**` as a user override, while [commands/z-amend.md](/Users/zeke/dev/z-harness/commands/z-amend.md:145) sends modified task blocks for reclassification, so previously auto-stamped modified tasks will keep stale tiers unless the old stamp is stripped or the classifier gets explicit “ignore existing auto stamp” context.

- **Major:** `/z-amend` narrows “modified tasks” to only Files / Acceptance / `**Tests:**` changes. [commands/z-amend.md](/Users/zeke/dev/z-harness/commands/z-amend.md:145) and [skills/z-amend/SKILL.md](/Users/zeke/dev/z-harness/skills/z-amend/SKILL.md:145) miss title, dependency, `REMOTE_VERIFY`, and `DOCS` changes, any of which can materially change classification and violates the stated “new/modified tasks” re-stamp requirement.

- **Major:** `/z-implement-next` states the retry override but has no retry dispatch path that can actually use it. [commands/z-implement-next.md](/Users/zeke/dev/z-harness/commands/z-implement-next.md:52) says cycle ≥ 2 forces Opus, but after review it only says to apply findings directly and then mark done, with no second implementer `Agent(..., model="opus")` call; the skill mirror has the same gap.

- **Major:** The missing-stamp fallback says to log `missing_complexity_stamp`, but the command docs do not define the concrete `log-event.sh` call, payload shape, or warning namespace. [commands/z-implement-next.md](/Users/zeke/dev/z-harness/commands/z-implement-next.md:50) is especially under-specified compared with other logging steps, so the “default to Sonnet, log warning” behavior is likely to be implemented inconsistently or skipped.
