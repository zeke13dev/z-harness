---
description: Investigate a known-bad behavior with explicit repro / hypothesis / evidence / isolation phases, then ship a fix using the /z-plan-light flow, then write a post-mortem with preventative action items. Cross-LLM consult at the hypothesis stage and again at the fix stage. Auto-bails to /z-plan when scope grows beyond architectural change.
argument-hint: <symptom description>
---

You are running **z-harness `/z-debug`** — investigation pipeline for an existing bug. Target: ≤30 min wall time end-to-end for a typical localized bug; can take longer if reproduction is difficult.

Symptom (from `$ARGUMENTS`):

$ARGUMENTS

**If empty** — `AskUserQuestion`: "What's the symptom?" before proceeding.

## Setup

1. **Derive slug** like `debug-<symptom-slug>` (e.g. "MLB doubleheaders mislabeled" → `debug-mlb-doubleheaders-mislabeled`). Confirm via `AskUserQuestion` if non-obvious or might collide.
2. Export `Z_HARNESS_SLUG=<slug>`.
3. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
4. `mkdir -p z-harness/$Z_HARNESS_SLUG/archive/$RUN/transcripts`.
5. **Version stamp + log:**
   ```bash
   VERSION_BLOB="$(bash "${CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["symptom"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" debug_run_start "$START_PAYLOAD"
   ```
6. Record start time `T0_DEBUG=$(date -u +%Y-%m-%dT%H:%M:%SZ)` — used for post-mortem timeline.
7. If `docs/llm/INDEX.json` exists → read it.

## Auto-bail thresholds (check throughout)

If at any phase you discover:

- Root cause spans **multiple modules** / requires **architectural change**
- Fix will touch **>5 files** OR introduces a **new public surface / wire format / schema**
- More than **3 hypothesis-isolation cycles** without convergence
- The bug is symptomatic of a broader design flaw rather than a localized defect

→ STOP. Write `z-harness/$Z_HARNESS_SLUG/escalation.md` documenting findings so far. Push-notify: "Debug requires architectural change — recommend `/z-plan` to design properly." Do not improvise a sprawling fix.

## Phase 1 — Problem statement

Ask clarifying questions via `AskUserQuestion`:

- "What was the expected behavior?"
- "What actually happens?"
- "When did this start?" (last working commit / deploy if known)
- "Reproducible?" (always / sometimes / once)
- "Any recent changes that might be related?"

Free-text follow-ups are fine for any of these.

Write `z-harness/$Z_HARNESS_SLUG/PROBLEM.md`:

```markdown
# Problem: <slug>

**Reported:** <T0_DEBUG>
**Reproducible:** <always | sometimes | once>
**Started:** <last-good ref or "unknown">

## Expected behavior
<verbatim from user>

## Actual behavior
<verbatim from user>

## Suspected scope
<one-paragraph initial read of where the bug likely lives>

## Recent changes mentioned by user
<verbatim or "none">
```

## Phase 2 — Reproduce + gather evidence

Try to reproduce. Methods (in priority order):

1. **Failing log/error already provided** by the user → read it.
2. **Failing test** → run it inline (or via `remote-runner` Haiku if remote build needed).
3. **Failing CLI/script** → run it; capture stdout/stderr.
4. **Production-only** → ask user for log timestamps; use `qt-bot-remote` skill (if available) or other log access to fetch the relevant slice. **DB queries** here stay with the main thread (interpretive), not `remote-runner` (which refuses DB).
5. **DB state snapshot** → if the bug involves data shape, query the DB read-only via `qt-bot-remote` to confirm the actual state matches the user's description.

Write `z-harness/$Z_HARNESS_SLUG/EVIDENCE.md`:

```markdown
# Evidence: <slug>

## Repro steps
1. ...
2. ...

## Captured output
```
<verbatim error/log/output>
```

## Relevant log lines
<grepped, with timestamps>

## Relevant DB / data state
<query results, if applicable>

## Reproducibility confirmed
<yes | no | partial; if no, explain>
```

**If cannot reproduce.** Halt and ask the user via `AskUserQuestion`:
- "Gather more evidence — what should I look at next?"
- "Proceed on inference only (risky — debug without repro is unreliable)"
- "Abandon — wait until repro is possible"

Default recommendation: gather more evidence. Debug-on-inference often fixes the wrong thing.

## Phase 3 — Hypothesize

Read relevant files (use `docs/llm/INDEX.json` to scope). Propose **2-3 hypotheses**, ranked by likelihood. For each:

- **Hypothesis:** <one-sentence statement of what's broken>
- **Supporting evidence:** <which lines in EVIDENCE.md point to this>
- **Refuting evidence:** <what would prove it wrong>
- **How to test:** <concrete experiment>

Save this list — it will go into the cross-LLM consult.

## Phase 4 — Bundled cross-LLM consult on hypotheses

Spawn both in parallel:

```
Agent(
  subagent_type="gemini-consultant",
  description="Debug hypotheses consult (Gemini) for <slug>",
  prompt="MODE: debug-hypotheses\n\nProblem (verbatim from PROBLEM.md):\n<content>\n\nEvidence (verbatim from EVIDENCE.md):\n<content>\n\nMy ranked hypotheses:\n<list of 2-3 from Phase 3>\n\nRelevant code (quoted with file:line):\n<short snippets>\n\nAsk: (a) which hypothesis do you find most plausible and why? (b) any hypotheses I missed? (c) for the top hypothesis, what's the cheapest experiment to confirm/refute? Be concrete."
)
Agent(
  subagent_type="codex-consultant",
  description="Debug hypotheses consult (Codex) for <slug>",
  prompt="MODE: debug-hypotheses\n\n<same prompt body>"
)
```

When both return:

1. **One reason it might be wrong** for each recommendation.
2. **Re-rank hypotheses** factoring in both consultants' input.
3. **Cross-LLM agreement** on top hypothesis = high-confidence; isolate that one first. **Disagreement** = surface to user via `AskUserQuestion`; let user pick the next experiment.

## Phase 5 — Isolate (test top hypothesis)

Run a focused experiment. Options (in priority order):

- Add a targeted log statement or assertion, re-run, observe.
- Write a minimal isolated test case (in the existing test framework) that exercises the hypothesized code path.
- DB query to confirm/refute data shape.
- File diff between known-good ref and current ref (`git diff <ref>..HEAD -- <suspect-files>`).
- `remote-runner` for a focused cargo build / cargo test if needed.

Write `z-harness/$Z_HARNESS_SLUG/ISOLATION.md`:

```markdown
# Isolation: <slug>

## Cycle <N>
**Hypothesis tested:** <statement>
**Experiment:** <what you did>
**Result:** <what you observed>
**Conclusion:** confirmed | refuted | inconclusive
```

**If top hypothesis is refuted** → loop back to Phase 3 with refined hypotheses (incorporating what you just learned). **Cap at 3 cycles.** If no convergence after 3 → halt and ask the user; auto-bail trigger may apply.

**If confirmed** → proceed to Phase 6.

## Phase 6 — Root cause + fix (reuses `/z-plan-light` Phases 3-9)

You now have a confirmed root cause. The remainder of `/z-debug` is structurally a `/z-plan-light`:

1. **Synthesize root cause + propose fix.** Write a fix statement that names the file(s) to change and the approach.
2. **Bundled cross-LLM consult on the FIX** — mode `light-fix`. Same shape as `/z-plan-light` Phase 3.
3. **Synthesize + push back.** One-reason-it-might-be-wrong per recommendation. Flag shortcuts.
4. **Present + approve.** `AskUserQuestion` with the synthesized fix.
5. **Write `FIX.md`** alongside the existing PROBLEM/EVIDENCE/ISOLATION docs:
   ```markdown
   # Fix: <slug>
   ## Problem
   <link/summary from PROBLEM.md>
   ## Root cause (confirmed)
   <link/summary from ISOLATION.md>
   ## Approach
   ...
   ## Files to change
   ## Acceptance
   ## Cross-LLM consensus
   ## Approved shortcuts
   ## Docs touched
   ```
6. **Inline implementation** (same as `/z-plan-light` Phase 7).
7. **Codex review** (same as `/z-plan-light` Phase 8 — non-negotiable).

Auto-bail still active: if the fix turns out to touch >5 files or introduce architectural change, halt and recommend `/z-plan`.

## Phase 7 — Post-mortem

**After the codex review passes**, write `z-harness/$Z_HARNESS_SLUG/POSTMORTEM.md`. This is mandatory for `/z-debug` (not just paperwork — surfaces preventative gaps):

```markdown
# Post-mortem: <slug>

## Summary
<2-3 sentences: what happened, impact, time-to-resolution>

## Timeline
- <T0_DEBUG>            — symptom first observed (per PROBLEM.md)
- <T_PHASE2>            — repro confirmed (per EVIDENCE.md)
- <T_ROOT_CAUSE>        — root cause identified (per ISOLATION.md final cycle)
- <T_FIX_SHIPPED>       — fix shipped (codex review passed)
- Total wall time: <delta>

## Root cause
<one-paragraph explanation. Reference PROBLEM.md, EVIDENCE.md, ISOLATION.md by section.>

## Fix
- Files changed: <from FIX.md>
- Summary: <one paragraph>

## Why we didn't catch it earlier
Pick at least one. Be honest:
- Spec gap — `<which spec section was missing or wrong>`
- Test gap — `<which test should have caught this>`
- Missing assertion — `<where>`
- Monitoring/alerting gap — `<what would have surfaced this in prod>`
- Doc gap — `<which docs/llm/ concept didn't mention this invariant>`
- Other — `<explain>`

## Action items (preventative)
- [ ] <regression test path + what it should cover>
- [ ] <SPEC.md / docs/llm/<concept>.json update with the invariant that was violated>
- [ ] <monitoring/alerting addition>
- [ ] <other follow-ups>

## Confidence
- **Root cause confidence:** <yes | partial — explain>
- **Similar bugs likely elsewhere?** <list any places worth auditing; or "none — this is localized">
```

After writing, ask the user via `AskUserQuestion`:
- "Convert action items into follow-up tasks?" → If yes, the orchestrator appends them to a designated `TASKS.md` (user picks which slug, or creates a fresh `audit-<topic>` slug) and the user can later `/z-implement-all` them.
- "Convert regression-test action items into a /z-test follow-up" → For each action item shaped like `Add regression test ...`, record the invariant + failure-class + target-file hint into `z-harness/<slug>/test-followups.md` (a flat list of seed entries shaped like Phase 2 drafts in `/z-test`). On the next `/z-plan` + `/z-test` cycle (or if the user re-runs `/z-test` on this same slug after seeding follow-up production tasks), these become mandatory TESTS.md entries. Closes the post-mortem loop automatically — the next plan run cannot ship without the regression test the post-mortem flagged.
- "Just record and move on" → leave POSTMORTEM.md as a standalone record.

Push-notify: "Post-mortem ready: `z-harness/<slug>/POSTMORTEM.md`. Action items: <N> (converted to tasks: <yes/no>)."

## Phase 8 — Finalize

1. Log:
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" debug_run_end \
     "$(printf '{"status":"shipped","hypothesis_cycles":%d,"action_items":%d}' "$CYCLES" "$N_ACTIONS")"
   ```
2. Push-notify if policy != `off`: "Debug complete. Root cause: <one-line>. Post-mortem and FIX.md in `z-harness/$Z_HARNESS_SLUG/`."

## Artifacts produced

- `z-harness/<slug>/PROBLEM.md` — Phase 1
- `z-harness/<slug>/EVIDENCE.md` — Phase 2
- `z-harness/<slug>/ISOLATION.md` — Phase 5 (one section per cycle)
- `z-harness/<slug>/FIX.md` — Phase 6
- `z-harness/<slug>/POSTMORTEM.md` — Phase 7 (post-ship)
- `z-harness/<slug>/archive/<run-id>/` — transcripts, diff.patch, reviewer output

## Hard rules

- **Never debug without repro.** If repro is impossible and user picks "proceed on inference," document that decision in PROBLEM.md and flag in POSTMORTEM.md confidence section.
- **Never skip the post-mortem.** Even on a trivial bug — the preventative action-items habit is what makes /z-debug different from /z-plan-light.
- **Never proceed past auto-bail thresholds** without explicit user override.
- **Always emit cross-LLM consult at hypothesis stage AND fix stage** — two separate cross-LLM rounds.
- **Always emit codex review** post-implementation — the safety gate is non-negotiable.
- **No emojis** anywhere in artifacts.
