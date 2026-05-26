MODE: light-fix

# Compaction Cadence — breakpoint trigger decisions (D2, D3, D6)

## Background

The z-harness orchestrator (`/z-implement-all`, `/z-review-all`) cannot self-monitor token usage and cannot self-invoke `/compact` or `/clear`. Instead, it must pause execution at strategic breakpoints, push-notify the user ("Usage at N%; pausing. Reply or re-invoke the command to resume."), and cleanly halt. On re-invocation, the orchestrator resumes from durable state (TASKS.md), picking up at the next pending task.

The goal: **prevent context degradation during long uninterrupted runs** (observed failure mode: task fails with `unable_to_complete` after retry=4 in a multi-hour run; no usage-% guard was ever wired up; zero `usage_pause` events in qt-bot metrics history).

## D2. Primary breakpoint trigger in /z-implement-all

When should the orchestrator pause to offer `/compact` or `/clear`?

**Options:**

(a) **Every N completed tasks** (default N=5).  
   *Tentative.* Pros: simple, predictable, works across all task types. Cons: coarse-grained (5 fast 2-min tasks = 10 min; 5 slow 10-min tasks = 50 min). May pause too often or too late depending on task profile.

(b) **Every N batches of up to 3 parallel tracks** (default N=2).  
   Pros: batching is the natural sync boundary in the orchestrator's main loop. Cons: unpredictable wall time per batch (one batch might have 3 parallel tracks; next might have 1).

(c) **Cumulative implementer-subagent count** (default 8, retries count).  
   Pros: costs subagent spawns are the actual token sink (SPEC/PLAN/TASKS reads, full implementer prompt). Cons: reviewer spawns are ~40% of implementer cost, so counting only implementer underweights review pressure. Retries inflate the count artificially.

(d) **Multi-trigger (a OR wall-time)** (default 5 tasks OR 30 min).  
   Pros: bounds both iteration count and elapsed wall time. Cons: adds complexity and env-var juggling.

**Which option is best?** Be concrete about edge cases (retry-heavy tasks, slow tasks, parallelism).

---

## D3. Add breakpoint in /z-review-all before Phase 4?

Phase 4 (consultant spawn) is **the heaviest single context burn** in the harness:
- `consultant-primary` reads SPEC.md + PLAN.md + TASKS.md + cumulative.diff + docs/llm/*.json in one go.
- `consultant-secondary` (Codex) does the same.
- If cumulative.diff > 500k lines, LLMs will struggle.

**Options:**

(a) **Yes** — pre-Phase-4 push notification: "About to spawn consultants; `/compact` first if needed, then re-invoke `/z-review-all` to resume from Phase 4."  
   *Tentative.* Pros: catches the known high-context-burn moment. Cons: one-shot command (not a loop), so user might forget to compact; adds a manual pause to an otherwise fire-and-forget workflow.

(b) **No** — review-all is already one-shot; user can manually `/compact` before invoking if needed.  
   Pros: no extra pauses, simpler command. Cons: no guard; if diff is large, consultants fail or return low-quality findings.

**Recommendation?** Is the pre-Phase-4 pause worth the UX friction?

---

## D6. Recommend /clear or /compact in the resume message?

When the orchestrator pauses for context (e.g., "Usage at 87%; pausing. Reply or re-invoke `/z-implement-all` to resume."), should the message recommend:

(a) **`/compact`** — preserves a summary of prior work in the main-thread history (easier to debug what happened if something breaks on resume).

(b) **`/clear`** — orchestrator's resume is fully idempotent (re-reads TASKS.md, picks next pending task), so clearing loses nothing but reclaims ~70% of context. Much safer for a long loop.  
   *Tentative.* 

**Edge cases to consider:**
- If the user manually edited TASKS.md between pause and resume, does `/clear` hide that?
- If a subagent crash happened mid-batch, does `/clear` let the orchestrator recover cleanly?
- Is `/compact` ever necessary for debugging the orchestrator itself?

---

## Constraints

- Keep answer ≤350 words total.
- Be concrete (cite specific token counts, wall-time bounds, or code patterns).
- Flag any interactions between D2, D3, D6 (e.g., if D2 pauses every 5 tasks, `/clear` is safe; if D2 is wall-time-only, `/compact` might be needed to track recent decisions).
