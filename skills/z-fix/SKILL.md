---
name: z-fix
description: Lightweight bug-fix command for the case where the user already has a diagnosis. Captures problem + repro, single light-fix sanity consult ("does the proposed cause explain all symptoms?"), inline implementation, non-negotiable Codex review. Optional post-mortem (auto-suggested if review needed >1 retry). Early gate recommends /z-debug if user signals unknown root cause.
argument-hint: <symptom or proposed fix description>
audience: user
driver_features_required: [subagent, ask_user]
---

You are running **z-harness `/z-fix`** — a fast path for bugs where you already know the root cause. Target: ≤15 min wall time end-to-end.

Task (from `$ARGUMENTS`):

$ARGUMENTS

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the question
     "What's the symptom and your hypothesis for the cause?" via their native
     channel. Silent omission is forbidden. -->
**If the task above is empty** — use `AskUserQuestion` to ask "What's the symptom and your hypothesis for the cause?" before proceeding. Do not invent.

This command is for **targeted fixes with a known diagnosis**. If at any phase you realize scope is broader or the root cause is unclear, STOP and recommend `/z-debug` instead.

## Setup

1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "null pointer on login" → `fix-null-pointer-login`). Check for an existing slug collision first (`bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" all_plan_slugs` to detect matching slugs across both new and legacy plan layouts). **If a collision is found, prompt the user via `AskUserQuestion` to confirm or choose a different slug. This collision check runs UNCONDITIONALLY and is never bypassed by the resolver below.**

   After the collision check passes (no collision found, or the user confirmed a new slug), apply the soft non-obvious-slug confirmation gate:

   ```bash
   # Only reached after collision check has already passed.
   RESOLVED="$(python3 scripts/config.py resolve-question workflow.slug_confirm)"
   RESOLVE_EXIT=$?

   if [[ $RESOLVE_EXIT -ne 0 ]]; then
     # Exit codes: 2=bad invocation, 3=unknown question_id, 4=I/O error.
     # In all error cases, fall through to ask the user normally — never silently skip.
     echo "resolve-question failed (exit $RESOLVE_EXIT); falling back to ask" >&2
     RESULT="ask"; DEFAULT=""; SOURCE="error"
   else
     RESULT="$(echo "$RESOLVED" | jq -r .result)"
     DEFAULT="$(echo "$RESOLVED" | jq -r .default)"
     SOURCE="$(echo "$RESOLVED" | jq -r .source)"
   fi
   ```

   Branch on `$RESULT`:
   - `skip`: accept the derived slug silently — no AskUserQuestion. Emit `askuser_skipped` event with `{question_id: "workflow.slug_confirm", source: "$SOURCE"}`.
   - `prefill`: present the AskUserQuestion normally, pre-select the derived slug as the recommended option (label suffix: ` (Recommended — your preference)`).
   - `ask`: if non-obvious, confirm via `AskUserQuestion` normally. If `$SOURCE == "conflict"`, add to the question header: `(Note: config says <X>, memory says <Y> — your answer below will be offered as a conflict-resolution write target.)` After the user picks an answer that differs from both stored values, surface a one-shot follow-up: "Record your answer as the new preference? (config / memory:very_strong / memory:strong / no)".
   - `halt`: emit `fix_halt` event and exit cleanly — do NOT invoke `AskUserQuestion`. Pre-preflight: nothing is registered yet, so this is a plain exit, not a teardown:
     ```bash
     if [[ "$RESULT" == "halt" ]]; then
       bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "${RUN:-z-fix}" fix_halt \
         "$(printf '{"reason":"no_ask_blocked","question_id":"workflow.slug_confirm","rule_id":"no_ask_halt"}')"
       echo "halt: no_ask_blocked on workflow.slug_confirm" >&2
       exit 0
     fi
     ```

   **Invariant:** the collision check above is a hard safety prerequisite that runs unconditionally regardless of resolver outcome. The resolver only governs the soft non-obvious-slug confirmation gate.

2. **Preflight ceremony (single call).** `scripts/z-preflight.sh` owns resolve/session-id/RUN-stamp/claim/register/run-brief-init/run_start/kernel-resolve, in that fixed order (contract: script header; LEDGER T005). `/z-fix` is a WRITE command — it claims (no `--no-claim`):
   ```bash
   # Capture BEFORE eval — $? after eval loses the script's exit-code contract.
   PREFLIGHT_OUT="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-preflight.sh" \
     --command /z-fix --slug "$Z_HARNESS_SLUG" \
     --intent "<symptom + hypothesis from \$ARGUMENTS — max 240 chars; not the command name alone>")"
   PREFLIGHT_RC=$?
   [ "$PREFLIGHT_RC" -eq 0 ] && eval "$PREFLIGHT_OUT"
   ```
   On success, `RUN`, `Z_HARNESS_PLAN_DIR`, `CURRENT_ARCHIVE_DIR`, `Z_HARNESS_SESSION_ID`, `CLAIM_HELD`, `REG_RC`, `KERNEL_PATH` are exported (script header is the source of truth). Run-brief is initialized as part of this call — registry `/z-fix`, profile `full`, artifact `FIX.md`:
   ```bash
   export RUN_BRIEF_PROFILE=full
   export RUN_BRIEF_ARTIFACT="$Z_HARNESS_PLAN_DIR/FIX.md"
   export RUN_BRIEF_ARTIFACT_FALLBACKS=""
   ```
   When `KERNEL_PATH` is non-empty, inject `kernel_path: <KERNEL_PATH>` as a line in the `Agent(prompt=...)` of both Phase 3 consultant dispatches; omit the line when empty (the agent's static fallback self-resolves).

   **Standard contention/corrupt-lock/register-failure menu** (documented once in the `z-preflight.sh` header; `/z-plan` Setup step 2 is the canonical writer instance — this is z-fix's deviations only, SKILL-STYLE.md §2):
   - **Contention (`PREFLIGHT_RC==10`)** — nothing was created. `AskUserQuestion` — proceed anyway / abort / use a new slug.
     - proceed anyway → re-run the SAME preflight call with `--no-claim` appended and continue uncoordinated; log a `fix_claim_override` event.
     - abort → `exit 1`. (Nothing was ever created.)
     - use a new slug → re-derive a slug once (loop-guard: at most 1 re-derive; if the new slug also contends, abort) and re-run the original claiming preflight call on it.
   - **Corrupt lock (`PREFLIGHT_RC==11`)** — same shape; manual-cleanup hint (`rm <claims_dir>/<slug>.lock*` then retry). `AskUserQuestion` — abort (default) / proceed UNCOORDINATED (`--no-claim`; log a `fix_claim_corrupt_proceed` event).
   - **Register failure (`REG_RC != 0` on `PREFLIGHT_RC==0`)** — graduated, not a hard stop (z-preflight.sh already warned on stderr); `RUN`/`Z_HARNESS_PLAN_DIR`/run-brief already exist. `AskUserQuestion` — proceed without coordination (continue; the claim is still held; skip heartbeats/deregister later) / abort (run **Run Brief — halt finalize** below with reason `active-plan registry register failed`, status `escalated`).

3. **Log fix run start** (domain-specific fields the generic wrapper `run_start` event doesn't carry):
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" fix_run_start "$START_PAYLOAD"
   ```
4. Notification policy: see [docs/human/config.md](docs/human/config.md) (notify.level key).
5. Initialize `REVIEW_CYCLES=0` counter (used in Phase 9 post-mortem trigger).
6. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.

## Auto-bail thresholds (check throughout)

At any phase, if you discover:

- **>5 candidate files** need editing
- **>2 non-obvious decisions** (per the rules `/z-plan` uses: new dep, public API change, algorithm with materially different tradeoffs, persistence change)
- **Cross-module / cross-crate impact** (the fix touches multiple modules, public APIs, wire formats, or schemas)
- **The user explicitly says** "this might be bigger than I thought"

→ STOP. Write `$Z_HARNESS_PLAN_DIR/escalation.md` describing what you found. Do not proceed to implementation. Run **Run Brief — halt finalize** (below) with reason `scope grew past fix-mode thresholds` and status `escalated`.

## Phase 0 — Wrong-tool gate (NON-SKIPPABLE)

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the wrong-tool
     gate question via their native channel. Silent omission is forbidden. -->
Before any exploration, ask via `AskUserQuestion`:

> "Do you already have a hypothesis for what's causing this?"
> - `yes — proceed with /z-fix` (default)
> - `no — recommend /z-debug` (will exit)
> - `modify hypothesis — let me refine it first` (free-text follow-up, then loop back to this question)

If user picks **no** → output one line: "Root cause unknown — run `/z-debug <symptom>` to start a hypothesis-driven investigation." Then run **Run Brief — halt finalize** (below) with reason `wrong tool — no hypothesis` and status `wrong_tool`. Do not continue.

This gate is non-skippable even if the user passed an argument. A symptom description alone is not a hypothesis.

## Phase 1 — Problem + repro + quick exploration (combined)

**Premise check.** Don't take the description for granted:
- Is this actually caused by the named hypothesis? Could the symptom have a different origin?
- Will fixing the proposed cause actually resolve the symptom?
- Is there a materially simpler fix path the user hasn't considered?

If any concern surfaces → raise it with the user conversationally — explain the concern and the better path in prose, **not** an `AskUserQuestion` popup — before proceeding. Don't plan around a flawed premise.

**Capture problem + evidence inline:**

Write an `## Evidence` section to `$Z_HARNESS_PLAN_DIR/archive/$RUN/phase1-context.md` with:
- The symptom (quoted if log/error output)
- The repro steps or failing test
- The proposed hypothesis (user's stated diagnosis)
- Any confirming or contradicting signals already observed

These become sections in FIX.md at Phase 6.

**Quick exploration:**
1. **If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) FIRST** — cheapest grounding available:
   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to the user and skip the Agent() call. The doc-fetcher result grounds Phase 1 exploration; drivers that skip it should warn the user that doc context is unavailable. -->
   ```
   Agent(subagent_type="doc-fetcher",
         description="Doc context for <slug>",
         prompt="query: <one-sentence fix description>\nrepo_root: <abs path>\ndepth: standard")
   ```
2. After doc-fetcher returns (or if no INDEX.json), Read 3-5 source files MAX to fill gaps. **Do NOT spawn the `Explore` subagent** — too expensive for fix-mode. Use Read/Grep/Glob directly from main thread.

Output: 1-paragraph problem statement + 1-paragraph context (hypothesis + confirming evidence).

**Check auto-bail thresholds.** If reading reveals >5 candidate files or cross-module impact, bail now.

## Phase 2 — Single key decision

Most light fixes have ONE root question: "what's the right fix for this cause?" Articulate it explicitly.

If there are >2 truly non-obvious decisions (new dep, public API change, algorithm with materially different tradeoffs, persistence change), **bail to `/z-plan`** — the cross-decision interaction analysis is worth the overhead.

## Phase 3 — Bundled `light-fix` consult

Spawn both consultants in parallel in a single message. The consult question is framed around the user's hypothesis — NOT a generic "what's the best fix?" framing. When `KERNEL_PATH` is non-empty (Setup step 2), add `kernel_path: <KERNEL_PATH>` as a line in each prompt below.

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to the user and skip both Agent() calls. The consultant results inform Phase 4 synthesis; drivers that skip them should warn the user that cross-LLM consult is unavailable and hard rules require both Gemini and Codex consultants. -->
```
Agent(
  subagent_type="consultant-primary",
  description="Light-fix consult (Gemini) for <slug>",
  prompt="MODE: light-fix\n\nUser's proposed cause: <hypothesis>\n\nProblem: <1-paragraph symptom + repro>\nEvidence: <1-paragraph confirming/contradicting signals>\nKey decision: <what's the right fix for this specific cause?>\nCandidate options (if any): <list with one-line tradeoffs>\nRelevant code snippets:\n<short quoted code with file:line markers>\n\nAsk: Does this proposed cause explain ALL symptoms listed in the evidence above? If not, what is the gap? Recommend the fix approach with tradeoffs. Be concise — this is a targeted fix for a known cause, not a feature."
)
Agent(
  subagent_type="consultant-secondary",
  description="Light-fix consult (Codex) for <slug>",
  prompt="MODE: light-fix\n\n<same prompt body>"
)
```

Both transcripts archive themselves under `$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts/`.

## Phase 4 — Synthesize + push back

When both return:

1. **One reason it might be wrong.** For each recommendation, articulate one concrete reason it could be wrong before accepting it. Mechanical, not optional.
2. **Synthesize.** Make the final call yourself, citing what you weighed.
3. **Flag shortcuts.** If any option is a shortcut over the robust long-lasting solution, mark it explicitly — needs Phase 5 user approval.
4. **Cross-LLM disagreement.** If Gemini and Codex disagree substantively — or either flags that the proposed cause does NOT explain all symptoms — surface the disagreement to the user in Phase 5. Do not silently pick one side.

## Phase 5 — Approve

Send `PushNotification` (if policy != `off`): "Fix-mode decision ready for review."

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the Phase 5 approval question (approve / modify / abandon) and any shortcut approval questions via their native channel. Silent omission is forbidden. -->
Present the brief synthesis (3-5 bullets) as a conversational reply — **not** an `AskUserQuestion` popup — and end with your recommendation. Invite the user to reply:
- **Approve fix as proposed**
- **Modify** — describe the change to <X>
- **Abandon** — this isn't the right approach

For any flagged shortcut: surface it in the same reply — the shortcut, its tradeoff vs the robust path, and your recommendation — and ask for explicit approval conversationally (default to the robust path if not approved).

If user picks **Abandon** → write nothing more; run **Run Brief — halt finalize** (below) with reason `user abandoned fix` and status `abandoned`.

## Phase 6 — Write FIX.md

Write `$Z_HARNESS_PLAN_DIR/FIX.md`:

```markdown
# Fix: <slug>

**Run:** <RUN>
**Status:** approved (not yet shipped)
**Plugin version:** <z_harness_version from setup>

## Problem
<1 paragraph — symptom + repro>

## Hypothesis
<user's proposed cause>

## Evidence
<confirming + contradicting signals observed>

## Root cause
<1 paragraph — confirmed or refined diagnosis after consult>

## Approach
<concrete plan: what files change, what stays the same>

## Files to change
- `<abs path 1>`
- `<abs path 2>`

## Acceptance
- [ ] <criterion 1>
- [ ] <criterion 2>

## Cross-LLM consensus
- Gemini: <one-line recommendation + whether cause explains all symptoms>
- Codex:  <one-line recommendation + whether cause explains all symptoms>
- Synthesized call: <your decision + brief rationale>

## Approved shortcuts
<list each shortcut + why approved; or "none">

## Docs touched
<slug(s) from docs/llm/ matching changed files, or "none"; consumed by /z-maintain-docs later>
```

Note: FIX.md is the single artifact for this command. Problem, hypothesis, and evidence content live as sections within FIX.md — no separate PROBLEM.md or EVIDENCE.md files.

No SPEC.md / PLAN.md / TASKS.md generated. FIX.md is the whole plan.

## Phase 7 — Inline implementation (NO implementer subagent)

The orchestrator (you, in main thread) reads the files listed in FIX.md "Files to change" and applies the edits directly with the Edit / Write tools. For 1-5 file edits the main thread already has all the context — spawning a fresh implementer just doubles token cost.

**Apply the same self-check the implementer subagent would** (from `agents/implementer.md`):
1. No broad exception handlers added.
2. No scope expansion outside FIX.md's "Files to change" list.
3. No unsolicited validation / error paths.
4. No new public surface beyond what FIX.md describes.
5. No stale docstrings / comments left behind.

If you applied any fix from the checklist, reflect it in the run-brief outcome when material.

**Mid-implementation scope growth — halt, do not continue.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP immediately. Do NOT offer to continue or spawn a subagent — auto-bail is non-negotiable:

1. Write `$Z_HARNESS_PLAN_DIR/escalation.md` describing what you found (which new files or decisions surfaced and why they exceed fix-mode thresholds).
2. Run **Run Brief — halt finalize** (below) with reason `scope grew mid-implementation` and status `escalated`. The user must restart with `/z-plan`.

Hard limit: if you find yourself touching >7 files inline, halt regardless — that's no longer a fix-mode change.

## Phase 8 — Codex review (safety gate, non-negotiable)

This step is non-negotiable. Even in fix mode, post-implementation review is the correctness guarantee.

```bash
git diff > $Z_HARNESS_PLAN_DIR/archive/$RUN/diff.patch
```

Spawn the reviewer:

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to the user and skip the Agent() call. Codex review is non-negotiable per hard rules; drivers that skip it must warn the user that the safety gate has been bypassed. -->
```
Agent(
  subagent_type="reviewer",
  description="Codex review of <slug>",
  prompt="task id: <slug>\ntask description: <FIX.md Approach summary>\nacceptance criteria: <FIX.md Acceptance list>\ndiff.patch path: <abs path>\nchanged files: <abs paths from FIX.md>\nrelevant_docs (paths — verify the diff didn't break invariants stated here): <paths from FIX.md Docs touched>\n$BASE: $Z_HARNESS_PLAN_DIR  (read FIX.md yourself if you need more context)"
)
```

Increment `REVIEW_CYCLES` by 1.

Parse the return (already capped at 8 KB, blockers + majors only).

**On blockers or majors:**
- **First failure**: re-edit inline based on findings. Re-run `git diff`; if byte-identical to prior diff (you pushed back instead of editing), run **Run Brief — halt finalize** (below) with reason `no_change_on_retry` and status `escalated`. Otherwise re-spawn `reviewer` once. Increment `REVIEW_CYCLES` by 1.
<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the second-failure decision (proceed anyway / patch manually / abandon) via their native channel. Silent omission is forbidden. -->
- **Second failure**: `AskUserQuestion` — proceed anyway / patch manually / abandon. On **abandon**, run **Run Brief — halt finalize** (below) with reason `user abandoned after second review failure` and status `abandoned`. On proceed anyway or patch manually, continue inline (no halt).

**No blockers/majors** → accept.

## Phase 9 — Optional post-mortem

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the post-mortem decision (yes / skip) via their native channel. Silent omission is forbidden. -->
Ask via `AskUserQuestion`:

- **Default = NO** if `REVIEW_CYCLES <= 1`: "Write post-mortem? (optional — default: skip)"
- **Default = YES** if `REVIEW_CYCLES > 1`: "Review cycles: <REVIEW_CYCLES>. Suggesting post-mortem — simple fix may have been subtler than expected. Write post-mortem? (default: yes)"

Options: `yes — write post-mortem` | `no — skip`

If user picks **yes** → write `$Z_HARNESS_PLAN_DIR/POSTMORTEM.md`:

```markdown
# Post-mortem: <slug>

**Run:** <RUN>
**Date:** <date>

## Summary
<1-2 sentence synopsis>

## Timeline
<ordered list of events from symptom notice to fix shipped>

## Root cause
<precise statement — what code path, what condition>

## Fix
<what was changed and why>

## Why we didn't catch it
<test gap, review gap, or assumption that failed>

## Action items
- [ ] <follow-up 1>
- [ ] <follow-up 2>

## Confidence
<high|medium|low> — <one sentence on what would change this>
```

Note: the MR-review integration block is NOT triggered automatically in `/z-fix`. If needed, run `/z-mr-review` separately.

If user picks **no** → skip; nothing written.

## Phase 10 — Finalize

1. Update FIX.md `Status:` to `shipped` and check off the acceptance boxes you verified.
2. **Run Brief finalize (registry Phase 10).** Set registry artifact env, pre-seed outcome/next, then include the shared fragment before `fix_run_end`. Chat and push text are rendered from `run-brief.json` only — do not author independent completion prose.

   Build `$NEXT_JSON` from FIX.md: when **Docs touched** is non-empty, use `{"label":"Refresh affected docs","command":"/z-maintain-docs"}`; otherwise `{"label":"Done — no follow-up required","command":null}`.

   ```bash
   export RUN_BRIEF_PROFILE="full"
   export RUN_BRIEF_ARTIFACT="$Z_HARNESS_PLAN_DIR/FIX.md"
   export RUN_BRIEF_ARTIFACT_FALLBACKS=""

   RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
   bash "$RB_SH" set-section --run "$RUN" --section outcome \
     --value "Fix shipped. ${N_FILES} files changed; review passed (${REVIEW_CYCLES} review cycle(s))."
   NEXT_JSON_FILE="$(mktemp -t z-rb-next.XXXXXX.json)"
   printf '%s\n' "$NEXT_JSON" > "$NEXT_JSON_FILE"
   bash "$RB_SH" set-section --run "$RUN" --section next --json "$NEXT_JSON_FILE"
   rm -f "$NEXT_JSON_FILE"
   ```

   <!-- include: _fragments/run-brief-finalize.md -->

3. Log the domain-specific run end, then tear down (after the brief's `--require` gate; releases the claim, deregisters, emits the generic `run_end`):
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" fix_run_end \
     "$(printf '{"status":"shipped","files_changed":%d,"review_cycles":%d,"postmortem_written":%s}' \
        "$N_FILES" "$REVIEW_CYCLES" "$POSTMORTEM_WRITTEN")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
     --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-fix --status complete
   ```
   Where `$POSTMORTEM_WRITTEN` is `true` or `false`.

## Run Brief — halt finalize

Every terminal halt after Setup step 2's `z-preflight.sh` call has succeeded (i.e. `RUN` is exported) funnels through this same procedure — never a bespoke cleanup path (SKILL-STYLE.md §2). Set `<reason>` (outcome text) and `<status>` (`wrong_tool` | `escalated` | `abandoned`) at the call site, then run:

```bash
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="$Z_HARNESS_PLAN_DIR/FIX.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS=""
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
bash "$RB_SH" set-section --run "$RUN" --section next --json /dev/stdin <<'JSON'
{"label": "Review fix status and retry or escalate", "command": null}
JSON
```

<!-- include: _fragments/run-brief-finalize.md -->

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" fix_run_end \
  "$(printf '{"status":"%s","files_changed":%d,"review_cycles":%d,"postmortem_written":false}' \
     "<status>" "${N_FILES:-0}" "${REVIEW_CYCLES:-0}")"
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
  --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-fix --status aborted
exit 1
```

When `FIX.md` is missing (most halts, since it's written in Phase 6), the shared fragment auto-downgrades to **lite** (Intent + Outcome + Next).

## Hard rules

- **Never skip Codex review.** Fix mode cuts planning overhead, not correctness.
- **Never proceed past auto-bail thresholds** without explicit user override.
- **Always emit cross-LLM consult** — both Gemini and Codex in parallel, framed around "does this cause explain all symptoms?", not a generic fix framing.
- **Never overwrite an existing `$Z_HARNESS_PLAN_DIR/` directory** without asking the user.
- **No emojis** anywhere in artifacts.
- **Phase 0 is non-skippable.** If the user cannot name a hypothesis, the command exits with a `/z-debug` recommendation, even if an argument was passed.
- **Single bundled `light-fix` consult only.** Parallel Gemini + Codex, framed around "does this cause explain all symptoms?" — not a multi-round hypothesis generation flow.
- **No exit past the funnel.** Complete → Phase 10's teardown call; everything else after preflight → **Run Brief — halt finalize** above.

### Git history-rewrite safety

Before recommending any `git reset --hard HEAD~N`, `git commit --amend`, or interactive-rebase squash on a branch tracking an upstream: for each commit being rewritten, run `git branch -r --contains <sha>`. If the upstream ref appears, STOP — recommend rebase or new-commit instead, never silent rewrite. Force-push to main requires explicit per-incident user authorization with (i) list of overwritten commits and (ii) content-equivalence/superset demonstration.

---

Driver support requirements: see frontmatter `driver_features_required`. Non-supporting drivers **must surface and skip** any gated block — silent omission is forbidden. Each gated call site carries its own `<!-- RUNTIME-GATE: ... -->` comment immediately before the call; that is the single source of truth (SKILL-STYLE.md §1 — the closing conformance table is retired for rewritten skills).
