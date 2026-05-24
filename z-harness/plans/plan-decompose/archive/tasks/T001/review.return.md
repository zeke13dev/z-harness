stent` event and the cluster is marked failed.
+
+---
+
+## Phase 6 — Return
+
+Emit `cluster_planner_end` telemetry (see top of file). Then return a single message in this exact shape:
+
+```
+STATUS: ok
+CLUSTER_ID: <id>
+TASKS_COUNT: <N>
+DECISIONS_RESOLVED: <K>
+DECISIONS_ESCALATED: <M>
+FILES_TOUCHED: [<workspace-relative path>, <workspace-relative path>, ...]
+```
+
+Constraints on the return shape:
+
+- `DECISIONS_ESCALATED` is **always 0 when `STATUS: ok`**. If any decision is escalated, you have already returned `STATUS: decision_needed` in Phase 2 or Phase 3 — you never reach Phase 6 with un-resolved escalations.
+- `FILES_TOUCHED` is a JSON array of workspace-relative paths (relative to repo root), one per file referenced in any task's `**Files:**` line. Deduplicated. This is the fast-path summary; the main thread will validate it against re-parsing TASKS.md.
+- `TASKS_COUNT` is a positive integer; if your plan would produce 0 tasks, return `STATUS: spec_problem` instead — a cluster with no tasks is a planning failure.
+
+---
+
+## Non-ok return shapes
+
+Use these instead of `STATUS: ok` when appropriate:
+
+```
+STATUS: anti_nesting_violation
+CLUSTER_ID: <id>
+ancestor_manifest_path: <absolute path>
+```
+
+```
+STATUS: decision_needed
+CLUSTER_ID: <id>
+DECISION_ID: <id>-D<n>
+QUESTION: <one sentence>
+OPTIONS: [...]
+RECOMMENDED_OPTION: <label or "none">
+IMPACT: <one line>
+AFFECTED_FILES: [...]
+```
+
+```
+STATUS: spec_problem
+CLUSTER_ID: <id>
+issue: <one paragraph describing the spec-level problem>
+```
+
+```
+STATUS: unable_to_complete
+CLUSTER_ID: <id>
+reason: <one paragraph; e.g. missing required input field, doc-fetcher errored repeatedly, etc.>
+```
+
+On every non-ok return, still emit `cluster_planner_end` with the matching status before returning.
+
+---
+
+## Hard rules (summary)
+
+- **No `Explore` subagent.** Cost discipline — narrow scopes don't justify it. Use `doc-fetcher` (if INDEX.json present) or direct Read/Grep/Glob (≤10 file reads).
+- **No Codex/Gemini consult.** Cost discipline — no per-leaf cross-LLM in v1.
+- **Conservative on decision escalation.** Default up, not down. Better to escalate a borderline decision than to silently make a wrong call.
+- **One escalated decision per cycle.** Return on the first one; re-spawn handles the rest.
+- **Anti-nesting guard runs FIRST.** Before any reads, before any writes — the very first action.
+- **Telemetry bracketing is mandatory.** `cluster_planner_start` at the top, `cluster_planner_end` on every exit path.
+- **No emojis.**
+- **Do not edit any file outside `output-path`** except for the `archive/<run-id>/decisions.md` log file inside it. In particular, **do not** touch the parent `MANIFEST.md` — that is the main thread's job.

Scrutinize this code rigorously. Claude is prone to: over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope beyond the spec.

Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, and a suggested fix.

**OUTPUT BUDGET — respect strictly:**
- Total response under **8000 characters**.
- Report **blockers and majors only**. Skip minors and nits unless a "minor" hides a correctness bug — in which case promote it to major.
- One finding per bullet. Two sentences max per finding (one for the problem, one for the fix).
- No re-stating of code already in the diff. No summaries of what the code does. No restating the spec.
- If there are no blockers or majors, respond with exactly: `No blockers or majors found.` (plus an optional 1-line note if something needs the implementer's attention but is below the bar).
codex
- **Major** — `agents/cluster-planner.md:73`: The anti-nesting guard explicitly allows `z-harness/<root>/MANIFEST.md`, but the acceptance criterion says to walk slug-dir ancestors and refuse if any `MANIFEST.md` is found, returning `ancestor_manifest_path`. Remove the special-case allowance and make the guard fail on the first ancestor manifest, or clarify/update the upstream spec if the parent manifest is intentionally allowed.

- **Major** — `agents/cluster-planner.md:41` and `agents/cluster-planner.md:72`: The file gives conflicting ordering guarantees: telemetry must fire “at the very top,” while the anti-nesting guard is also “FIRST action, before anything else.” Resolve this by defining the exact permitted order, likely `cluster_planner_start` first for bracketing, then anti-nesting before any repo reads/writes, and adjust the “FIRST action” wording so implementers do not skip telemetry or run repo exploration before the guard.
2026-05-23T04:51:13.290578Z ERROR codex_core::session: failed to record rollout items: thread 019e532c-056a-7ec3-878b-774b0bcdccbd not found
tokens used
45,004
- **Major** — `agents/cluster-planner.md:73`: The anti-nesting guard explicitly allows `z-harness/<root>/MANIFEST.md`, but the acceptance criterion says to walk slug-dir ancestors and refuse if any `MANIFEST.md` is found, returning `ancestor_manifest_path`. Remove the special-case allowance and make the guard fail on the first ancestor manifest, or clarify/update the upstream spec if the parent manifest is intentionally allowed.

- **Major** — `agents/cluster-planner.md:41` and `agents/cluster-planner.md:72`: The file gives conflicting ordering guarantees: telemetry must fire “at the very top,” while the anti-nesting guard is also “FIRST action, before anything else.” Resolve this by defining the exact permitted order, likely `cluster_planner_start` first for bracketing, then anti-nesting before any repo reads/writes, and adjust the “FIRST action” wording so implementers do not skip telemetry or run repo exploration before the guard.
