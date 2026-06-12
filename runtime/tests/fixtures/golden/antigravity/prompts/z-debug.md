---
description: "Heavy hypothesis-tournament debugging pipeline for the case where root cause is unknown. Two rounds of adversarial multi-LLM hypothesis generation (Claude + Codex + Gemini), discriminating-test matrix with consensus-first ranking + forced outlier ..."
role: workflow
---

You are running **z-harness `/z-debug`** — heavy hypothesis-tournament pipeline for an existing bug whose root cause is unknown. This is the discipline path. If the user already has a working hypothesis they want to ship a fix for, Phase 0 will redirect them to `/z-fix`.

Symptom (from `$ARGUMENTS`):

$ARGUMENTS

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the question
     "What's the symptom?" via their native channel. Silent omission is forbidden. -->
**If empty** — `AskUserQuestion`: "What's the symptom?" before proceeding.

## Setup

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the slug
     confirmation question via their native channel if non-obvious. Silent
     omission is forbidden. -->
1. **Derive slug** like `debug-<symptom-slug>` (e.g. "MLB doubleheaders mislabeled" → `debug-mlb-doubleheaders-mislabeled`). Confirm via `AskUserQuestion` if non-obvious or might collide.
2. Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`.
3. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
5. **Version stamp + log:**
   ```bash
   export Z_HARNESS_SESSION_ID="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" session-id)"
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["symptom"] = sys.argv[2]; v["session_id"] = sys.argv[3]; v["command"] = "z-debug"
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>" "$Z_HARNESS_SESSION_ID")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" debug_run_start "$START_PAYLOAD"
   ```

   **Run Brief init (immediately after `debug_run_start`).** Registry: `/z-debug`, profile `full`, artifact `DEBUG.md`.
   ```bash
   CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"
   RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
   DEBUG_INTENT="$(python3 -c 'import json,sys; s=json.loads(sys.argv[1]).get("symptom","").strip(); print(("Debug: "+s)[:240] if s else "Debug unknown root cause")' "$START_PAYLOAD")"
   bash "$RB_SH" init --run "$RUN" --command /z-debug --slug "$Z_HARNESS_SLUG" --profile full --intent "$DEBUG_INTENT"
   export RUN_BRIEF_PROFILE=full
   export RUN_BRIEF_ARTIFACT="$Z_HARNESS_PLAN_DIR/DEBUG.md"
   export RUN_BRIEF_ARTIFACT_FALLBACKS=""
   ```

   **Active-plan registration (immediately after debug_run_start).** Register this run in the shared registry. Graduated failure policy — never silent-continue on failure:
   ```bash
   python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" register \
     --run-id "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-debug --phase debug \
     --session "$Z_HARNESS_SESSION_ID"
   REG_RC=$?
   ```
   - `REG_RC == 0` → registered; proceed.
   - `REG_RC == 3` (no record written) → emit `registry_error` event; interactive → `AskUserQuestion` proceed/abort; unattended → proceed+log (or halt if `Z_HARNESS_STRICT_OVERLAP=1`). No deregister on abort (no record).
   - Any OTHER nonzero → treat as `REG_RC == 3`.
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" registry_error \
     "$(printf '{"op":"register","run_id":"%s","rc":%d}' "$RUN" "$REG_RC")"
   ```

   **FINALIZE_STATUS rule:** On any run-ending halt after `REG_RC == 0`, run **Run Brief — halt finalize** (below), set `FINALIZE_STATUS=aborted`, then `deregister --status aborted`. On normal completion (Phase 10 shipped or abandoned branches), deregister with `complete`. If register failed, do NOT deregister.

   **Kernel path resolution (once per run, immediately after debug_run_start):**
   ```bash
   KERNEL_PATH="$(bash scripts/resolve-kernel.sh 2>/dev/null || true)"
   ```
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

   Then log provider resolution (once per run, guarded against re-emission):
   ```bash
   if [ ! -f "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged" ]; then
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-providers.sh" || true
     mkdir -p "$Z_HARNESS_PLAN_DIR/archive/$RUN"
     touch "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged"
   fi
   ```
6. Record start time `T0_DEBUG=$(date -u +%Y-%m-%dT%H:%M:%SZ)` — used for post-mortem timeline.
7. If `docs/llm/INDEX.json` exists → note it. Phase 2 (Evidence) and Phase 3a (Round 1 hypotheses) will dispatch `doc-fetcher` (Haiku) instead of reading INDEX.json or per-concept JSONs from main thread. The orchestrator never reads `docs/llm/*.json` directly.

8. **Soft cost estimate (non-blocking).** Call the gate helper and display the estimate. No AskUser, no halt — always proceeds.
   ```bash
   # workflow.pre_run_cost_gate
   COST_GATE_JSON="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/pre-run-cost-gate.sh" \
     z-debug soft "$RUN" 2>/dev/null)" || COST_GATE_JSON=""
   if [ -n "$COST_GATE_JSON" ]; then
     COST_HUMAN_BLOCK="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("human_block",""))' "$COST_GATE_JSON" 2>/dev/null || true)"
     [ -n "$COST_HUMAN_BLOCK" ] && printf '%s\n' "$COST_HUMAN_BLOCK"
     COST_ESTIMATED_TOKENS="$(python3 -c 'import json,sys; e=json.loads(sys.argv[1]).get("estimate",{}); print(json.dumps(e.get("estimated_tokens")))' "$COST_GATE_JSON" 2>/dev/null || echo "null")"
     COST_CONFIDENCE="$(python3 -c 'import json,sys; e=json.loads(sys.argv[1]).get("estimate",{}); print(e.get("confidence","unknown"))' "$COST_GATE_JSON" 2>/dev/null || echo "unknown")"
     COST_BASIS="$(python3 -c 'import json,sys; e=json.loads(sys.argv[1]).get("estimate",{}); print(e.get("basis","unknown"))' "$COST_GATE_JSON" 2>/dev/null || echo "unknown")"
   fi
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cost_gate_decision \
     "$(python3 -c 'import json,sys; print(json.dumps({"command":"z-debug","choice":"auto_proceed","reason":"soft_gate","estimated_tokens":json.loads(sys.argv[1]),"confidence":sys.argv[2],"basis":sys.argv[3]}))' \
        "${COST_ESTIMATED_TOKENS:-null}" "${COST_CONFIDENCE:-unknown}" "${COST_BASIS:-unknown}")"
   ```

## Auto-bail thresholds (softened — heavy path)

If at any phase you discover that the root cause / fix requires any of:

- **Multiple modules** / cross-module impact
- **Architectural change**
- **New public surface** / new wire format / new schema

→ STOP. Write `$Z_HARNESS_PLAN_DIR/escalation.md` documenting findings so far. Do not improvise a sprawling fix. Per the FINALIZE_STATUS rule, run **Run Brief — halt finalize** with reason `architectural change — recommend /z-plan`, then deregister before exiting.

The old `>5 files touched` trigger is **dropped** — `/z-debug` is the heavy path, larger localized fixes are expected. Cycle cap is enforced separately in Phase 6 (soft warning at 3, hard halt at 6).

## Phase 0 — Wrong-tool gate (non-skippable)

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the wrong-tool
     gate question via their native channel. Silent omission is forbidden. -->
`AskUserQuestion`:

**"Do you already have a concrete hypothesis for what's causing this?"**

- **"no — proceed with /z-debug"** (default) — continue to Phase 1.
- **"yes — recommend /z-fix"** — exit with one-line recommendation: "You already have a diagnosis. Run `/z-fix <symptom>` for the lightweight fix-with-known-cause flow." Do not proceed. Per the FINALIZE_STATUS rule, run **Run Brief — halt finalize** with reason `wrong tool — user has diagnosis`, then deregister before exiting (this halt occurs after a successful register).

This gate is mandatory. If the user picks "yes," exit cleanly even if `$ARGUMENTS` was non-empty.

## Phase 1 — Problem statement

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the problem
     clarification questions via their native channel. Silent omission is forbidden. -->
Ask clarifying questions via `AskUserQuestion`:

- "What was the expected behavior?"
- "What actually happens?"
- "When did this start?" (last working commit / deploy if known)
- "Reproducible?" (always / sometimes / once)
- "Any recent changes that might be related?"

Free-text follow-ups are fine for any of these.

Open the unified artifact `$Z_HARNESS_PLAN_DIR/DEBUG.md`. Start with the header and the `## Problem` section:

```markdown
# Debug: <slug>

**Reported:** <T0_DEBUG>
**Reproducible:** <always | sometimes | once>
**Started:** <last-good ref or "unknown">

## Problem

### Expected behavior
<verbatim from user>

### Actual behavior
<verbatim from user>

### Suspected scope
<one-paragraph initial read of where the bug likely lives>

### Recent changes mentioned by user
<verbatim or "none">
```

All subsequent phases append sections to this **single `DEBUG.md` file**. There are no separate PROBLEM/EVIDENCE/ISOLATION/FIX/POSTMORTEM files.

## Phase 2 — Reproduce + Evidence Inventory

Try to reproduce. Methods (in priority order):

1. **Failing log/error already provided** by the user → read it.
2. **Failing test** → run it inline (or via `remote-runner` Haiku if remote build needed).
3. **Failing CLI/script** → run it; capture stdout/stderr.
4. **Production-only** → ask user for log timestamps; use `qt-bot-remote` skill (if available) or other log access to fetch the relevant slice. **DB queries** here stay with the main thread (interpretive), not `remote-runner` (which refuses DB).
5. **DB state snapshot** → if the bug involves data shape, query the DB read-only via `qt-bot-remote` to confirm the actual state matches the user's description.

**Feedback-loop escalation ladder.** Goal: produce a deterministic, agent-runnable pass/fail signal. Try strategies in this order — stop at the first one that yields a clean pass/fail:

1. **Failing unit test** — if a test already exists that exercises the code path, run it directly.
2. **`curl`/CLI one-liner** — a single shell invocation whose exit code or stdout unambiguously signals pass/fail.
3. **CLI output diff** — capture expected vs actual output; diff exits non-zero on divergence.
4. **Playwright/browser script** — for UI or HTTP regressions; automates the browser interaction and asserts on DOM state or response code.
5. **Trace replay** — replay a captured request trace against the current code; assert on matching response or behavior.
6. **Throwaway harness** — minimal ad-hoc test file that exercises the suspect code path; discard after isolation.
7. **Fuzz loop** — short fuzzing run over the failing input space; useful when the input boundary triggering the bug is unclear.
8. **`git bisect run`** — for regressions with a known-good baseline; see Phase 2.5 for the full bisect fast-path. Do not re-implement bisect here — Phase 2.5 handles it.
9. **Differential run vs known-good** — run the same command on two versions (e.g. a pinned dependency or a branch snapshot) and diff outputs.
10. **HITL bash script** — hand the user a script they run manually and paste back stdout/stderr; last resort when full automation is blocked by auth, network, or hardware constraints.

If none of the above yields a deterministic signal, document why in the Evidence Inventory and use the soft AskUser valve below.

Append `## Evidence Inventory` to `DEBUG.md`:

```markdown
## Evidence Inventory

### Repro steps
1. ...
2. ...

### repro_confidence
<high | low | none>
<!-- high = deterministic, agent-runnable pass/fail signal achieved (via ladder above);
     low  = partial repro or repro requires manual steps;
     none = cannot reproduce; explain in a following line -->
<!-- Previously "Reproducibility confirmed: yes|no|partial" — this field supersedes it. -->

### Inventory
- **EVID-001:** <text or quoted log line / fixture / metric>
- **EVID-002:** <text>
- **EVID-003:** <text>
- ...
```

**Each evidence entry gets a stable `EVID-NNN` ID at capture time** (zero-padded, 3 digits). These IDs are referenced by Phase 7's Evidence coverage table — never renumber, never reuse.

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the cannot-
     reproduce gate (gather more evidence / proceed on inference / abandon) via
     their native channel. Silent omission is forbidden. -->
**If cannot reproduce.** Halt and ask the user via `AskUserQuestion`:
- "Gather more evidence — what should I look at next?"
- "Proceed on inference only (risky — debug without repro is unreliable)"
- "Abandon — wait until repro is possible"

Default recommendation: gather more evidence. Debug-on-inference often fixes the wrong thing.

## Phase 2.5 — Regression bisect (conditional fast-path)

When the bug is a regression with a known-good baseline and a scriptable repro, `git bisect run` deterministically locates the offending commit + line-level diff without any LLM reasoning. This phase is a **fast-path evidence augmentation** — it never replaces the hypothesis tournament, only seeds it.

### Gate (all three must hold)

1. **`Started:` field from Phase 1 is not "unknown"** — user supplied a last-good ref / SHA / tag / branch.
2. **`repro_confidence: high`** in Phase 2's Evidence Inventory — `low` or `none` is insufficient.
3. **Repro is scriptable** — the orchestrator can produce a single shell command that exits 0 when the bug is absent (good) and non-zero when present (bad). If repro requires interactive input, multiple manual steps, or a long-running service, the repro is not scriptable — skip Phase 2.5.

If any gate fails → skip Phase 2.5 silently and proceed to Phase 3a unchanged. Do not push-notify the skip.

### Dispatch shape

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     fast-path only — pipeline continues to Phase 3a if skipped. -->
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="bisect-isolator",
  description="Bisect regression for <slug>",
  prompt="repro_command: <shell command, exit 0=good, non-zero=bad>\ngood_ref: <last-good SHA/tag/branch from Phase 1 Started field>\nbad_ref: HEAD\nrepo_root: <abs path>\ntask_id: <RUN>\n$BASE: $Z_HARNESS_PLAN_DIR"
)
```

The orchestrator constructs `repro_command` from Phase 2's repro steps. If Phase 2 captured the repro as a failing test, `repro_command` is typically `cargo test -p <crate> <test_name>` or `python -m pytest <path>::<test>`; if Phase 2 captured it as a CLI invocation, use that verbatim. The repro must be self-contained — bisect will run it ~log₂(N) times across the range.

### Handling the return

Parse the `STATUS:` line:

- **`STATUS: ok`** — bisect found the offending commit. Append a high-confidence evidence entry to the Evidence Inventory:

  ```markdown
  - **EVID-NNN:** (source: bisect) Offending commit `<offending_sha>` introduced the regression between `<good_ref>` and `<bad_ref>`. Files changed: `<list>`. Diff excerpt:
    ```diff
    <capped diff from bisect return>
    ```
  ```

  The `(source: bisect)` tag marks this entry as deterministically derived rather than observationally captured. Subsequent phases treat it the same as any other `EVID-NNN`.

  Then **seed Phase 3a's hypothesis-generation prompts** with the bisect result. Append a `Bisect result (high confidence):` block to the Round 1 prompt (immediately after Evidence Inventory) containing the offending SHA + diff excerpt. This shifts LLM attention from "where is the bug?" to "why did this specific change break things?" — which is the harder question bisect cannot answer mechanically.

- **`STATUS: bisect_unusable`** — repro didn't invert across the range, refs not found, or bisect was inconclusive. Append a one-line note to DEBUG.md Evidence Inventory:

  ```markdown
  _Phase 2.5 bisect skipped: <reason from STATUS return>._
  ```

  Proceed to Phase 3a unchanged. Bisect's unusability is informative — `repro_passes_on_bad_ref` may indicate the bug is intermittent (Phase 2's "Reproducibility confirmed" was overclaimed); `repro_fails_on_good_ref` may indicate this is not actually a regression (the "good" baseline already had the bug). Mention this hint in the Phase 3a prompt as context, but do not derive hypotheses from it.

- **`STATUS: refused`** — caller-side issue (destructive repro script, dirty working tree, interpretive_work request). Record the refusal as a one-line note in Evidence Inventory (`_Phase 2.5 bisect refused: <reason>._`) and proceed to Phase 3a unchanged. Bisect never blocks the pipeline — refused is one more reason to fall through, not a halt-and-ask gate. If the user wants to rewrite the repro and retry bisect, they can re-invoke /z-debug after revising.

- **`STATUS: failed`** — bisect ran but couldn't converge (typically too many `skip` returns). Treat as `bisect_unusable` for routing purposes; the bisect log path is in the return for caller inspection.

### Hard limits

- **Bisect never blocks the pipeline.** All non-`ok` returns fall through to Phase 3a. The phase is a fast-path, not a gate.
- **Bisect never replaces hypothesis generation.** Even on `STATUS: ok` with a single-line diff in the offending commit, Phase 3a–6 still runs. Bisect tells you WHAT changed; hypothesis tournament tells you WHY it broke things. A refactor commit can expose a latent bug elsewhere; Round 1+2 adversarial rounds are still valuable for surfacing this.
- **Bisect's offending SHA does NOT pre-fill the winning hypothesis.** The Phase 6 fix-gate still requires `posterior == very_high` AND zero `unexplained` rows in the Evidence coverage table. The bisect evidence is one input among many.
- **Honor the orchestrator-only likelihood-bucket rule.** The bisect-isolator return is raw mechanical output, not a likelihood assignment. The orchestrator (and only the orchestrator) decides how the bisect result weights subsequent likelihood judgments.

## Phase 3a — Round 1 hypothesis generation (3 LLMs, parallel, independent)

**Contamination mitigation:** the orchestrator (Claude main thread) writes its OWN hypothesis block to a checkpoint file BEFORE dispatching the consultants. This prevents the orchestrator from re-reading consultant output and laundering it as "its own" hypothesis at merge time.

1. **Orchestrator checkpoint (FIRST).** Independently propose 3-5 hypotheses using the Round-1 schema. Write to `$Z_HARNESS_PLAN_DIR/archive/$RUN/round1-orchestrator.md`:

   ```markdown
   # Round 1 — Orchestrator hypotheses (checkpoint)

   _Written BEFORE consultant dispatch — do not edit after Phase 3a merge._

   | claim | prediction_if_true | prediction_if_false | discriminating_test | test_cost | parallel_safe | reasoning |
   |---|---|---|---|---|---|---|
   | ... | ... | ... | ... | free\|cheap\|medium\|expensive | true\|false | ... |
   ```

   `parallel_safe: true` only if the discriminating test mutates no shared state.

2. **Dispatch consultants in parallel (single message).** Each receives ONLY the Problem + Evidence Inventory sections of DEBUG.md (plus doc-fetcher synthesis if relevant). Never share the orchestrator's checkpoint block.

   Check the config knobs (resolve once here; reuse in subsequent phases):

   ```bash
   PERSONA_ROTATION="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get experiment.persona_rotation 2>/dev/null || echo "true")"
   CRITIQUE_PANEL="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get personas.critique_panel 2>/dev/null || echo "true")"
   ```

   **If `PERSONA_ROTATION == "true"`**, use the **fixed 5-member panel** (no randomness). Before dispatching, resolve persona prefixes (when `CRITIQUE_PANEL == "true"`) and emit `persona_bound` events for each arm:

   ```bash
   PLUGIN="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}"

   # Vanilla defaults: empty prefix for all 5 arms. Knob OFF (CRITIQUE_PANEL!=true OR
   # PERSONA_ROTATION!=true) leaves these untouched, so dispatch is byte-identical to before.
   AGY_PERSONA_PREFIX=""; CLAUDE_PERSONA_PREFIX=""; GROK_PERSONA_PREFIX=""
   COMPOSER_PERSONA_PREFIX=""; CODEX_PERSONA_PREFIX=""
   AGY_PERSONA_ID=""; CLAUDE_PERSONA_ID=""; GROK_PERSONA_ID=""
   COMPOSER_PERSONA_ID=""; CODEX_PERSONA_ID=""
   AGY_DRAW_ID=""; CLAUDE_DRAW_ID=""; GROK_DRAW_ID=""
   COMPOSER_DRAW_ID=""; CODEX_DRAW_ID=""

   if [ "$CRITIQUE_PANEL" = "true" ]; then
     # Draw up to 5 distinct consultant personas. GRACEFUL DEGRADATION: if the consultant
     # pool has fewer than 5 members, the subcommand returns a shorter array (or [] when
     # empty) and notes it on stderr — it never exits non-zero. Unfilled slots stay vanilla.
     PERSONAS_JSON=$(python3 "$PLUGIN/scripts/resolve-persona.py" random-distinct-for-role consultant --count=5 \
       2>>"$Z_HARNESS_PLAN_DIR/archive/$RUN/persona-draw.log")

     # Positional bind: [0]->agy, [1]->claude-sonnet, [2]->grok, [3]->composer, [4]->codex.
     # `// ""` yields an empty string for absent indices under underflow, so those arms run vanilla.
     for slot in 0:AGY 1:CLAUDE 2:GROK 3:COMPOSER 4:CODEX; do
       idx="${slot%%:*}"; who="${slot##*:}"
       pname=$(echo "$PERSONAS_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[$idx]['persona'] if $idx < len(d) else '')" 2>/dev/null || true)
       ppath=$(echo "$PERSONAS_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[$idx]['persona_body_path'] if $idx < len(d) else '')" 2>/dev/null || true)
       pdraw=$(echo "$PERSONAS_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[$idx]['draw_id'] if $idx < len(d) else '')" 2>/dev/null || true)
       [ -z "$pname" ] && continue   # underflow slot — leave vanilla
       prefix=$(python3 "$PLUGIN/runtime/dispatch/persona_prompt.py" "$ppath" "" 2>/dev/null | head -c 4096)
       eval "${who}_PERSONA_ID=\$pname"
       eval "${who}_PERSONA_PREFIX=\$prefix"
       eval "${who}_DRAW_ID=\$pdraw"
     done
   fi

   # Emit persona_bound for each arm. When CRITIQUE_PANEL==true and a persona was drawn,
   # use selection_source=random_role_pool_distinct and include persona_id + draw_id.
   # When no persona was drawn (vanilla slot or CRITIQUE_PANEL==false), use selection_source=fixed_panel.
   for slot in agy:AGY claude-sonnet:CLAUDE grok:GROK composer:COMPOSER codex-5.5:CODEX; do
     arm="${slot%%:*}"; who="${slot##*:}"
     eval "pid=\$${who}_PERSONA_ID"; eval "pdraw=\$${who}_DRAW_ID"
     if [ -n "$pid" ]; then
       bash "$PLUGIN/scripts/log-event.sh" "$RUN" persona_bound \
         "$(python3 -c 'import json,sys; print(json.dumps({"run_id":sys.argv[1],"command":"z-debug","role":"consultant","arm":sys.argv[2],"selection_source":"random_role_pool_distinct","phase":"3a","persona_id":sys.argv[3],"draw_id":sys.argv[4]}))' \
            "$RUN" "$arm" "$pid" "$pdraw")"
     else
       bash "$PLUGIN/scripts/log-event.sh" "$RUN" persona_bound \
         "$(printf '{"run_id":"%s","command":"z-debug","role":"consultant","arm":"%s","selection_source":"fixed_panel","phase":"3a"}' \
            "$RUN" "$arm")"
     fi
   done
   ```

   Then spawn all 5 panel members in parallel. Cursor arms pass their model via `--model <model>`. Each `<ARM_PERSONA_PREFIX>` is the persona body followed by a blank line (from the draw above), or **empty** when that arm drew no persona (underflow slot) or `CRITIQUE_PANEL` is OFF — in the empty case the prompt is byte-identical to the pre-persona dispatch.

   ```
   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
        <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
        Phase 3a cannot complete without subagent support. -->
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     subagent_type="agy",
     description="R1 hypothesis generation for <slug> — gemini arm",
     prompt="<AGY_PERSONA_PREFIX>MODE: generate-hypotheses-round1\n\nProblem (verbatim):\n<## Problem section>\n\nEvidence Inventory (verbatim):\n<## Evidence Inventory section>\n\nRelevant code (quoted with file:line, brief):\n<short snippets>\n\ndoc-fetcher synthesis (if relevant):\n<synthesis>\n\nAsk: independently propose 3-5 hypotheses for the root cause. Each must include a discriminating test that confirms if true AND refutes if false. Do not assume any context outside the problem statement and evidence inventory provided.\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
   )
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     subagent_type="cursor",
     model="claude-4.6-sonnet",
     description="R1 hypothesis generation for <slug> — claude-sonnet arm",
     prompt="<CLAUDE_PERSONA_PREFIX>MODE: generate-hypotheses-round1\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
   )
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     subagent_type="cursor",
     model="grok-4.3",
     description="R1 hypothesis generation for <slug> — grok arm",
     prompt="<GROK_PERSONA_PREFIX>MODE: generate-hypotheses-round1\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
   )
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     subagent_type="cursor",
     model="composer-2.5",
     description="R1 hypothesis generation for <slug> — composer arm",
     prompt="<COMPOSER_PERSONA_PREFIX>MODE: generate-hypotheses-round1\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
   )
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     subagent_type="codex-cli",
     description="R1 hypothesis generation for <slug> — codex-5.5 arm",
     prompt="<CODEX_PERSONA_PREFIX>MODE: generate-hypotheses-round1\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
   )
   ```

   **If `PERSONA_ROTATION == "false"`**, fall back to the standard 2-consultant dispatch:

   ```
   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
        <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
        Phase 3a cannot complete without subagent support. -->
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     subagent_type="consultant-secondary",
     description="R1 hypothesis generation for <slug>",
     prompt="MODE: generate-hypotheses-round1\n\nProblem (verbatim):\n<## Problem section>\n\nEvidence Inventory (verbatim):\n<## Evidence Inventory section>\n\nRelevant code (quoted with file:line, brief):\n<short snippets>\n\ndoc-fetcher synthesis (if relevant):\n<synthesis>\n\nAsk: independently propose 3-5 hypotheses for the root cause. Each must include a discriminating test that confirms if true AND refutes if false. Do not assume any context outside the problem statement and evidence inventory provided.\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
   )
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     subagent_type="consultant-primary",
     description="R1 hypothesis generation for <slug>",
     prompt="MODE: generate-hypotheses-round1\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
   )
   ```

3. **Merge.** After all consultants return:
   - Read the orchestrator checkpoint FROM DISK (`archive/$RUN/round1-orchestrator.md`) — NOT from conversation state.
   - **If `PERSONA_ROTATION == "true"`** (5-panel path): merge all six lists (orchestrator + gemini, claude-sonnet, grok, composer, codex-5.5) into a single `## Hypothesis Pool` section in DEBUG.md. Tag each row `proposed_by: [models]` and `overlap_count: N` (1–6 — how many of the six sources contained this hypothesis).
   - **If `PERSONA_ROTATION == "false"`** (2-consultant path): merge all three lists (orchestrator + consultant-primary + consultant-secondary) into a single `## Hypothesis Pool` section in DEBUG.md. Tag each row `proposed_by: [models]` and `overlap_count: N` (1, 2, or 3 — how many of the three sources contained this hypothesis).
   - Assign each row a stable ID `H<NNN>` (zero-padded, 3 digits).
   - **Semantic dedup uses the exact written text of each row, not the orchestrator's recall of intent.** Two rows with the same `claim` text (or close paraphrase, judged by content not source) merge into one row with `overlap_count += 1`. Each merge decision is documented as a one-line note alongside the merged row (e.g., `_merged: H003 (orchestrator) + H007 (codex) — same claim about cache key collision._`).

   Append to DEBUG.md:

   ```markdown
   ## Hypothesis Pool

   | id | claim | proposed_by | overlap_count | prediction_if_true | prediction_if_false | discriminating_test | test_cost | parallel_safe |
   |---|---|---|---|---|---|---|---|---|
   | H001 | ... | [orchestrator, codex] | 2 | ... | ... | ... | cheap | true |
   | H002 | ... | [gemini] | 1 | ... | ... | ... | medium | false |
   ```

## Phase 3b — Round 2 adversarial

Single-message parallel dispatch with `MODE: generate-hypotheses-round2-adversarial`. Each receives ONLY the merged `## Hypothesis Pool` section (surgical extraction per the Phase-visibility matrix), plus Problem + Evidence Inventory. **Do NOT** include Test Matrix, Experiment Log, or Score Updates — those don't exist yet anyway.

**If `PERSONA_ROTATION == "true"`**, use the fixed 5-panel. Before dispatching, reuse the persona prefixes drawn in Phase 3a (same draw, same positional binding — `AGY_PERSONA_PREFIX`, `CLAUDE_PERSONA_PREFIX`, etc. are still set). Emit `persona_bound` events for each arm at phase 3b, carrying the same `persona_id` + `draw_id` from the Phase 3a draw (or `selection_source=fixed_panel` for vanilla slots):

```bash
for slot in agy:AGY claude-sonnet:CLAUDE grok:GROK composer:COMPOSER codex-5.5:CODEX; do
  arm="${slot%%:*}"; who="${slot##*:}"
  eval "pid=\$${who}_PERSONA_ID"; eval "pdraw=\$${who}_DRAW_ID"
  if [ -n "$pid" ]; then
    bash "$PLUGIN/scripts/log-event.sh" "$RUN" persona_bound \
      "$(python3 -c 'import json,sys; print(json.dumps({"run_id":sys.argv[1],"command":"z-debug","role":"consultant","arm":sys.argv[2],"selection_source":"random_role_pool_distinct","phase":"3b","persona_id":sys.argv[3],"draw_id":sys.argv[4]}))' \
         "$RUN" "$arm" "$pid" "$pdraw")"
  else
    bash "$PLUGIN/scripts/log-event.sh" "$RUN" persona_bound \
      "$(printf '{"run_id":"%s","command":"z-debug","role":"consultant","arm":"%s","selection_source":"fixed_panel","phase":"3b"}' \
         "$RUN" "$arm")"
  fi
done
```

Then spawn all 5 panel members in parallel. Cursor arms pass their model via `--model <model>`. Each `<ARM_PERSONA_PREFIX>` is the same prefix from Phase 3a (persona body + blank line), or **empty** for vanilla slots — in the empty case the prompt is byte-identical to the pre-persona dispatch:

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     Phase 3b cannot complete without subagent support. -->
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="agy",
  description="R2 adversarial for <slug> — gemini arm",
  prompt="<AGY_PERSONA_PREFIX>MODE: generate-hypotheses-round2-adversarial\nschema_version: hypothesis_round2_v1\n\nProblem (verbatim):\n<## Problem>\n\nEvidence Inventory (verbatim):\n<## Evidence Inventory>\n\nHypothesis Pool (verbatim, with H<NNN> IDs):\n<## Hypothesis Pool table>\n\nAsk: given this merged hypothesis pool, return exactly TWO markdown tables in this order. Do not restate existing pool entries — your value is orthogonality and critique, not endorsement.\n\nTABLE 1 — NEW hypotheses (orthogonality hunt — failure modes absent from the pool). Columns (exact, in order):\n| claim | prediction_if_true | prediction_if_false | discriminating_test | test_cost | parallel_safe | reasoning | orthogonality_to |\n  - `test_cost` ∈ {free, cheap, medium, expensive}\n  - `parallel_safe` ∈ {true, false} — true ONLY if the discriminating test mutates no shared state\n  - `orthogonality_to` — comma-separated list of H<NNN> IDs this row fills a gap relative to (e.g. `H001, H004`)\n\nTABLE 2 — CRITIQUES of existing pool rows. Columns (exact, in order):\n| target_id | critique_type | problem | recommended_action | merge_with_id |\n  - `target_id` — H<NNN> of the row being critiqued (required; rows missing this will be dropped)\n  - `critique_type` MUST be one of: `non_discriminating_test`, `false_parallel_safe`, `duplicate`, `weak_claim`, `unclear_prediction`\n  - `problem` — concrete description; no 'looks good', no 'agree', no empty cells, no pure restatement of the target row's claim\n  - `false_parallel_safe` rows MUST cite the specific mutation in the `problem` cell (e.g. 'writes to ~/.cache/foo'), not just 'mutates state'\n  - `merge_with_id` — populated ONLY when `critique_type == duplicate` (the H<NNN> the target should merge into)\n\nTag the response with `schema_version: hypothesis_round2_v1` at the top.\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="cursor",
  model="claude-4.6-sonnet",
  description="R2 adversarial for <slug> — claude-sonnet arm",
  prompt="<CLAUDE_PERSONA_PREFIX>MODE: generate-hypotheses-round2-adversarial\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="cursor",
  model="grok-4.3",
  description="R2 adversarial for <slug> — grok arm",
  prompt="<GROK_PERSONA_PREFIX>MODE: generate-hypotheses-round2-adversarial\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="cursor",
  model="composer-2.5",
  description="R2 adversarial for <slug> — composer arm",
  prompt="<COMPOSER_PERSONA_PREFIX>MODE: generate-hypotheses-round2-adversarial\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="codex-cli",
  description="R2 adversarial for <slug> — codex-5.5 arm",
  prompt="<CODEX_PERSONA_PREFIX>MODE: generate-hypotheses-round2-adversarial\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
```

**If `PERSONA_ROTATION == "false"`**, fall back to the standard 2-consultant dispatch:

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     Phase 3b cannot complete without subagent support. -->
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-secondary",
  description="R2 adversarial for <slug>",
  prompt="MODE: generate-hypotheses-round2-adversarial\nschema_version: hypothesis_round2_v1\n\nProblem (verbatim):\n<## Problem>\n\nEvidence Inventory (verbatim):\n<## Evidence Inventory>\n\nHypothesis Pool (verbatim, with H<NNN> IDs):\n<## Hypothesis Pool table>\n\nAsk: given this merged hypothesis pool, return exactly TWO markdown tables in this order. Do not restate existing pool entries — your value is orthogonality and critique, not endorsement.\n\nTABLE 1 — NEW hypotheses (orthogonality hunt — failure modes absent from the pool). Columns (exact, in order):\n| claim | prediction_if_true | prediction_if_false | discriminating_test | test_cost | parallel_safe | reasoning | orthogonality_to |\n  - `test_cost` ∈ {free, cheap, medium, expensive}\n  - `parallel_safe` ∈ {true, false} — true ONLY if the discriminating test mutates no shared state\n  - `orthogonality_to` — comma-separated list of H<NNN> IDs this row fills a gap relative to (e.g. `H001, H004`)\n\nTABLE 2 — CRITIQUES of existing pool rows. Columns (exact, in order):\n| target_id | critique_type | problem | recommended_action | merge_with_id |\n  - `target_id` — H<NNN> of the row being critiqued (required; rows missing this will be dropped)\n  - `critique_type` MUST be one of: `non_discriminating_test`, `false_parallel_safe`, `duplicate`, `weak_claim`, `unclear_prediction`\n  - `problem` — concrete description; no 'looks good', no 'agree', no empty cells, no pure restatement of the target row's claim\n  - `false_parallel_safe` rows MUST cite the specific mutation in the `problem` cell (e.g. 'writes to ~/.cache/foo'), not just 'mutates state'\n  - `merge_with_id` — populated ONLY when `critique_type == duplicate` (the H<NNN> the target should merge into)\n\nTag the response with `schema_version: hypothesis_round2_v1` at the top.\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-primary",
  description="R2 adversarial for <slug>",
  prompt="MODE: generate-hypotheses-round2-adversarial\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
```

**Orchestrator post-process (filter step) — apply each filter explicitly:**

For NEW rows:
- (a1) **Inter-consultant dedup (apply FIRST).** Merge the NEW tables from all returning consultants into a single candidate list. Before assigning H<NNN> IDs, dedup the candidate list against itself using the same text-only semantic dedup rule from Phase 3a (compare `claim` text / close paraphrase, judged by content). If multiple panel members proposed the same NEW hypothesis, collapse into a single candidate row with `proposed_by` listing all sources; document each merge as a one-line note. Do NOT assign two separate H<NNN> IDs for the same claim.
  - **5-panel path (`PERSONA_ROTATION == "true"`):** merge NEW tables from all five arms (gemini, claude-sonnet, grok, composer, codex-5.5).
  - **2-consultant path (`PERSONA_ROTATION == "false"`):** merge NEW tables from both consultants. If both Codex and Gemini proposed the same NEW hypothesis, collapse into a single candidate row with `proposed_by: [codex, gemini]`.
- (a2) **Pool dedup (apply SECOND).** Drop any surviving candidate NEW row whose `claim` semantically duplicates an existing pool row (same dedup rule; document the drop).

For CRITIQUES:
- (b) Drop any critique row missing a `target_id: H<NNN>` cell.
- (c) Drop any critique row whose `problem` cell is tautological — `"agree"`, `"looks good"`, empty, or pure restatement of the target row's claim.
- (d) Drop any `false_parallel_safe` critique that does not cite a specific mutation in the `problem` cell (e.g., must say `"writes to ~/.cache/foo"`, not just `"mutates state"`).

**Apply surviving critiques and additions:**
- NEW rows: append each surviving candidate from step (a2) to Hypothesis Pool with a new `H<NNN>` ID. Set `proposed_by` to the merged list from step (a1). Recompute `overlap_count = len(set(proposed_by))` — never arithmetic-sum.
  - **5-panel path:** `overlap_count` can range 1–6 (orchestrator + up to 5 panel arms). Prior assignment in Phase 4 uses: `≥3 → high`, `2 → med`, `1 → low`.
  - **2-consultant path:** `overlap_count` capped at 3 (e.g. `[codex]`, `[gemini]`, or `[codex, gemini]` if both proposed it).
- `non_discriminating_test` / `weak_claim` / `unclear_prediction` critiques: refine the target row's `discriminating_test` / `claim` / `prediction_*` cells (or, if irreparable, drop the row and note in `## Eliminated Alternatives`).
- `false_parallel_safe` critiques: flip the target row's `parallel_safe` from `true` to `false`.
- `duplicate` critiques: merge `target_id` into `merge_with_id` — union the two rows' `proposed_by` lists (set-union, no duplicates), recompute `overlap_count = len(set(proposed_by))`, then drop the duplicate row. Never arithmetic-sum the old `overlap_count` values.
  - **5-panel path:** the independent sources are {orchestrator, gemini, claude-sonnet, grok, composer, codex-5.5}; `overlap_count` reflects how many of these six sources proposed the surviving row.
  - **2-consultant path:** the independent sources are {orchestrator, codex, gemini}; `overlap_count` capped at 3, which the Phase 4 `prior` table supports.

Commit the updated `## Hypothesis Pool` to DEBUG.md after Phase 3b.

## Phase 4 — Build the Test Matrix

Append `## Test Matrix` to DEBUG.md. Schema header documented at the top of the section:

```markdown
## Test Matrix

_Schema: `id` (H<NNN> from Hypothesis Pool); `claim` (one-line); `proposed_by` (model list);
`overlap` (1-3); `prior` (mechanical from overlap: 3→high, 2→med, 1→low);
`test` (the discriminating test); `cost` (free|cheap|medium|expensive);
`parallel` (true|false); `status` (active|eliminated)._

| id | claim | proposed_by | overlap | prior | test | cost | parallel | status |
|---|---|---|---|---|---|---|---|---|
| H001 | ... | [orchestrator, codex] | 2 | med | ... | cheap | true | active |
| H002 | ... | [gemini] | 1 | low | ... | medium | false | active |
```

**Prior assignment is mechanical from `overlap_count`:** `3 → high`, `2 → med`, `1 → low`. No subjective adjustment. Initial `status` is always `active`.

## Phase 5 — Compute test order (consensus-first + forced outlier carve-out)

Sort the active rows by `overlap` descending (consensus first — higher overlap reflects three independent LLMs converging on the same failure mode).

**Forced outlier carve-out (groupthink mitigation):** always insert the top 2 unique-to-one-model rows (`overlap == 1`) near the front of the test order — within the first 3-4 positions, even if their `prior` is `low`. The orthogonality these surface is exactly what consensus-only ranking destroys.

Document the chosen order in DEBUG.md as a one-line note under the Test Matrix (e.g., `_Test order (cycle 1): H001, H004, H002 (outlier carve-out), H005 (outlier carve-out), H003._`).

## Phase 6 — Batch isolation cycle (loop)

For the current cycle (start at cycle 1):

1. **Group active hypotheses by `parallel`.** Run all `parallel: true` tests as a batch — in parallel where the test environment permits, or at minimum in series without intervening edits to shared state. Run `parallel: false` tests serially.

2. **Likelihood assignment — orchestrator only.** The orchestrator (Claude main thread) ALONE reads raw test output and assigns each tested hypothesis a likelihood bucket from:

   ```
   {strongly_falsified, weakly_falsified, inconclusive, weakly_supported, strongly_supported}
   ```

   Never delegate this to a consultant. Never pass raw test output to a consultant. Record in DEBUG.md `## Experiment Log` (cycle N section):

   ```markdown
   ## Experiment Log

   ### Cycle 1
   - **H001:** test = `<command>`; output snippet:
     ```
     <≤10 lines verbatim>
     ```
     Likelihood = `strongly_supported`. Rule: <one-sentence justification — what in the output drove the bucket>.
   - **H002:** ...
   ```

3. **Apply the posterior lookup table** (verbatim — this is the locked scoring rule):

   | prior \ likelihood    | strongly_falsified | weakly_falsified | inconclusive | weakly_supported | strongly_supported |
   |---|---|---|---|---|---|
   | **high** (overlap=3)  | eliminated         | low              | high         | high             | very_high          |
   | **med** (overlap=2)   | eliminated         | very_low         | med          | high             | very_high          |
   | **low** (overlap=1)   | eliminated         | very_low         | low          | med              | high               |

   Posterior order: `very_high > high > med > low > very_low > eliminated`.

   Update Test Matrix `status` column: `eliminated` for any row whose likelihood was `strongly_falsified`; `active` otherwise. Record the posterior bucket as a per-row annotation (either a new column or a one-line note under the row).

4. **Append `## Score Updates`** (cumulative, one block per cycle):

   ```markdown
   ## Score Updates

   ### Cycle 1
   - H001: prior=med + likelihood=strongly_supported → posterior=very_high (rule fired: med×strongly_supported)
   - H002: prior=low + likelihood=strongly_falsified → posterior=eliminated (rule fired: any×strongly_falsified)
   ...
   ```

   Hypotheses formed when `repro_confidence` is `low` or `none` carry lower initial credence and are tagged "unverified — needs a clean repro to validate."

5. **Move eliminated rows** to a `## Eliminated Alternatives` section (preserve the row + the cycle that eliminated it + the falsifying test):

   ```markdown
   ## Eliminated Alternatives
   - **H002** (eliminated cycle 1): claim=`...`; falsified by `<discriminating_test>` — output showed `...`.
   ```

### Phase 6 loop logic

- **Fix-gate check:** if any active hypothesis has `posterior == very_high` AND there is a written causal mechanism (Phase 7's Root Cause draft) explaining every `EVID-NNN` in the Evidence Inventory → fix-gate open, proceed to Phase 7.
- **Otherwise:** increment cycle counter, return to Phase 6 step 1 with the remaining `active` rows in updated test order.
- **Soft warning at cycle 3** — push-notify: "z-debug cycle 3 reached without convergence. Two cycles remaining before hard halt."
<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the hard cycle
     cap gate (continue / bail to /z-plan / abandon) via their native channel.
     Silent omission is forbidden. -->
- **Hard cycle cap: 5.** If cycle 6 would be needed, halt and `AskUserQuestion`:
  - `continue (override cap)` — explicit user override required to enter cycle 6+.
  - `bail to /z-plan` — write `escalation.md`, recommend `/z-plan`. Per the FINALIZE_STATUS rule, run **Run Brief — halt finalize** with reason `cycle cap — bailed to /z-plan`, then deregister before exiting.
  - `abandon` — log `debug_run_end {status: "abandoned"}` and stop (the abandoned finalize branch in Phase 10 handles deregister).
- **Pool collapse (all eliminated, no `very_high` survivor):** optionally spawn a **Round 3 generation pass**.

### Optional Round 3 (pool-collapse recovery)

Counts as one of the 5 cycle slots. Dispatch the orchestrator + both consultants per the Phase-visibility matrix:

- Consultant input is **restricted to facts, not judgments**: pass ONLY the eliminated `claim` text + the `discriminating_test` that falsified each. **Never** pass the likelihood bucket nor the posterior nor the full `## Eliminated Alternatives` section.
- MODE: `generate-hypotheses-round1` (re-use Round 1 schema — these are fresh hypotheses given the falsified-set context).
- Merge into Hypothesis Pool with new `H<NNN>` IDs; rebuild Test Matrix entries; continue Phase 6 loop.

## Phase 7 — Root cause + fix-gate + fix (reuses `/z-plan-light` mechanics)

Promote the winning hypothesis (the one with `posterior == very_high`) to a `## Root Cause` section in DEBUG.md:

```markdown
## Root Cause

**Winning hypothesis:** H<NNN>
**Posterior:** very_high
**Causal mechanism:** <paragraph explaining how this hypothesis produces every observed symptom>

### Evidence coverage

| evid_id | text | status | how_root_cause_handles_it |
|---|---|---|---|
| EVID-001 | <text from Evidence Inventory> | explained | <one sentence> |
| EVID-002 | <text> | falsifies_alternative | <which H-id, one sentence> |
| EVID-003 | <text> | orthogonal_with_reason | <reason it's noise not signal> |
```

**Statuses (locked):**
- `explained` — the root cause directly produces this evidence.
- `falsifies_alternative` — this evidence eliminated a competing hypothesis and is consistent with the root cause.
- `orthogonal_with_reason` — unrelated to root cause; the reason cell documents why it's noise.
- `unexplained` — placeholder; the fix-gate cannot open while any row carries this status.

**Fix-gate (hard, two preconditions — BOTH must hold):**
1. Winning hypothesis `posterior == very_high`.
2. Zero rows in the Evidence coverage table with `status == unexplained`.

If either fails: halt. Either upgrade the root cause statement (so it actually explains the unexplained row) or return to Phase 6 for additional experiments. Do not advance to fix on a partial story.

**Once the gate opens:**

1. Capture pre-fix SHA: `PRE_FIX_SHA=$(git rev-parse HEAD)`. Passed to `/z-mr-review` later as `--base`.
2. **Bundled `light-fix` consult on the proposed fix.** Dispatch consultants in parallel per the Phase-visibility matrix (subagents see: Problem + Evidence Inventory + winning Hypothesis Pool rows + Experiment Log + draft Root Cause + draft Evidence coverage table; subagents must NOT see Eliminated Alternatives or Score Updates history).

   **If `PERSONA_ROTATION == "true"`**, use the fixed 5-panel. Before dispatching, emit `persona_bound` events for each arm (same pattern as Phase 3a, with `"phase":"7"`):

   ```bash
   for ARM in gemini claude-sonnet grok composer codex-5.5; do
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" persona_bound \
       "$(printf '{"run_id":"%s","command":"z-debug","role":"consultant","arm":"%s","selection_source":"fixed_panel","phase":"7"}' \
          "$RUN" "$ARM")"
   done
   ```

   Spawn all 5 panel members in parallel. Cursor arms pass their model via `--model <model>`:

   ```
   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
        <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
        cannot complete without subagent support. -->
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
         prompt="MODE: light-fix\n\n<sections per Phase-visibility matrix row 7>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]")
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
         prompt="MODE: light-fix\n\n<same sections>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]")
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
         prompt="MODE: light-fix\n\n<same sections>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]")
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
         prompt="MODE: light-fix\n\n<same sections>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]")
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
         prompt="MODE: light-fix\n\n<same sections>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]")
   ```

   **If `PERSONA_ROTATION == "false"`**, fall back to the standard 2-consultant dispatch:

   ```
   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
        <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
        cannot complete without subagent support. -->
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
         prompt="MODE: light-fix\n\n<sections per Phase-visibility matrix row 7>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]")
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
         prompt="MODE: light-fix\n\n<same sections>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]")
   ```
3. **Synthesize + push back.** One reason it might be wrong per recommendation. Flag shortcuts.
<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the fix approval
     question via their native channel. Silent omission is forbidden. -->
4. **Present + approve.** `AskUserQuestion` with the synthesized fix.
5. **Write `## Fix Plan`** section to DEBUG.md (schema mirrors `/z-plan-light` Phase 6 FIX.md):

   ```markdown
   ## Fix Plan

   ### Approach
   ...

   ### Files to change
   - <path>: <what changes>

   ### Acceptance
   - ...

   ### Cross-LLM consensus
   ...

   ### Approved shortcuts
   ...

   ### Docs touched
   ...
   ```

6. **Inline implementation** (same as `/z-plan-light` Phase 7). Implementer self-check: no broad exception handlers, no scope expansion, no unsolicited validation, no new public surface, no stale comments.

   #### Git history-rewrite safety

   Before recommending any `git reset --hard HEAD~N`, `git commit --amend`, or interactive-rebase squash on a branch tracking an upstream: for each commit being rewritten, run `git branch -r --contains <sha>`. If the upstream ref appears, STOP — recommend rebase or new-commit instead, never silent rewrite. Force-push to main requires explicit per-incident user authorization with (i) list of overwritten commits and (ii) content-equivalence/superset demonstration.

7. **Codex review** (same as `/z-plan-light` Phase 8 — non-negotiable). Retry-once policy. Track `REVIEW_CYCLES`.

Auto-bail still active: if the fix turns out to require architectural change / new public surface / cross-module impact, halt and recommend `/z-plan`.

## Phase 8 — Verification

Append `## Verification` section to DEBUG.md. **Two mandatory items:**

1. **Regression test** tied to the winning hypothesis — at minimum, a test that fails on the pre-fix code and passes on the post-fix code. Record path + what it asserts.
2. **Coincidence check** — re-run the top eliminated alternative's discriminating test against the post-fix code and confirm it still produces the same falsifying signal it did during isolation. (Guards against accidentally "fixing" a parallel issue that masks the real one.)

```markdown
## Verification

### Regression test
- Path: <test file path>
- Asserts: <what it checks>
- Pre-fix: FAIL; Post-fix: PASS.

### Coincidence check (top eliminated alternative)
- Hypothesis re-tested: H<NNN> — `<claim>`.
- Discriminating test re-run: `<command>`.
- Pre-fix signal: `<falsifying signal>`. Post-fix signal: `<still same falsifying signal — confirms elimination wasn't a coincidence>`.
```

## Phase 9 — Post-mortem (mandatory)

Post-mortem is **non-negotiable** for `/z-debug`. Append `## Post-mortem` section to DEBUG.md:

```markdown
## Post-mortem

### Summary
<2-3 sentences: what happened, impact, time-to-resolution>

### Timeline
- <T0_DEBUG>            — symptom first observed
- <T_PHASE2>            — repro confirmed
- <T_ROOT_CAUSE>        — root cause identified (cycle <N>, posterior=very_high on H<NNN>)
- <T_FIX_SHIPPED>       — fix shipped (codex review passed)
- Total wall time: <delta>

### Root cause
<one-paragraph explanation, referencing H<NNN> and EVID-NNN IDs>

### Fix
- Files changed: <from Fix Plan>
- Summary: <one paragraph>

### Why we didn't catch it earlier
Pick at least one. Be honest:
- Spec gap — `<which spec section was missing or wrong>`
- Test gap — `<which test should have caught this>`
- Missing assertion — `<where>`
- Monitoring/alerting gap — `<what would have surfaced this in prod>`
- Doc gap — `<which docs/llm/ concept didn't mention this invariant>`
- Other — `<explain>`

### Action items (preventative)
- [ ] <regression test path + what it should cover>
- [ ] <SPEC.md / docs/llm/<concept>.json update with the invariant that was violated>
- [ ] <monitoring/alerting addition>
- [ ] <other follow-ups>

### Confidence
- **Root cause confidence:** <yes | partial — explain>
- **Similar bugs likely elsewhere?** <list any places worth auditing; or "none — this is localized">
```

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the MR-review
     gate question and the action-item conversion question via their native
     channel. Silent omission is forbidden. -->
After writing the Post-mortem section, ask the user via `AskUserQuestion` (before the action-item conversion prompts):

**"Run MR-style quality review on the fix diff?"**
- "Run MR-style review (Recommended)" — invoke `/z-mr-review` on the fix diff; P0/P1 findings will be appended to the post-mortem's preventative action items automatically.
- "Skip" — leave the post-mortem as-is and proceed to the action-item conversion prompts.

If user accepts:

1. Invoke `/z-mr-review` as a best-effort step (on any failure, append a note to the Post-mortem section and continue — do NOT halt the post-mortem):
   ```bash
   /z-mr-review --slug $Z_HARNESS_SLUG --base $PRE_FIX_SHA --force-on-trunk
   ```
   - `PRE_FIX_SHA` was captured at Phase 7. Pass it as `--base` so the diff covers exactly the fix changes.
   - `--force-on-trunk` allows the review to run on whatever branch `/z-debug` is operating from.
   - `/z-mr-review` already gates on `STYLE.md` existence and will refuse with "Run /z-style-init first." if it's missing. Do NOT try to handle this here — let it fail-fast. On failure, log "MR review skipped: STYLE.md missing" (or "MR review skipped: /z-mr-review failed — <reason>") and continue.
   - MR-REVIEW.md is written by `/z-mr-review` to the canonical path: `$(git rev-parse --show-toplevel)/$Z_HARNESS_PLAN_DIR/MR-REVIEW.md`.

2. If `/z-mr-review` succeeds, parse `$(git rev-parse --show-toplevel)/$Z_HARNESS_PLAN_DIR/MR-REVIEW.md` for P0/P1 findings using a defensive Python inline block (treat malformed/missing as "no findings" — never fall back to prose parsing):
   ```bash
   python3 - <<'PYEOF'
   import sys, yaml
   mr_path = "<abs_path_to_MR-REVIEW.md>"
   try:
       with open(mr_path) as f:
           raw = f.read()
       parts = raw.split("---")
       if len(parts) < 3:
           raise ValueError("No valid frontmatter found")
       fm = yaml.safe_load(parts[1])
       if not isinstance(fm, dict):
           raise ValueError("Frontmatter is not a mapping")
       findings = fm.get("findings_index")
       if not isinstance(findings, list):
           print("NOTE: findings_index missing or not a list — treating as no findings")
           sys.exit(0)
       for entry in findings:
           if not isinstance(entry, dict):
               continue
           sev = entry.get("severity", "")
           if sev in ("P0", "P1"):
               fid = entry.get("id", "T-MR-???")
               title = entry.get("title", entry.get("file", "<no title>"))
               print(f"- [ ] [{fid}] {title} (from MR-REVIEW.md quality review)")
   except FileNotFoundError:
       print("NOTE: MR-REVIEW.md not found — MR review produced no output")
   except (yaml.YAMLError, ValueError, KeyError) as e:
       print(f"NOTE: MR-REVIEW.md parse error ({e}) — treating as no findings")
   PYEOF
   ```
   Collect the printed lines. If no `- [ ]` lines were printed (no P0/P1 findings or parse fallback), use a single note: `- MR quality review found no P0/P1 findings.`

3. Append the collected finding lines (or the "no findings" note) to the Post-mortem section's "Action items (preventative)" list.

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the post-mortem
     action-item disposition question via their native channel. Silent omission
     is forbidden. -->
After writing, ask the user via `AskUserQuestion`:
- "Convert action items into follow-up tasks?" → If yes, the orchestrator appends them to a designated `TASKS.md` (user picks which slug, or creates a fresh `audit-<topic>` slug) and the user can later `/z-implement-all` them.
- "Convert regression-test action items into a /z-test follow-up" → For each action item shaped like `Add regression test ...`, record the invariant + failure-class + target-file hint into `$Z_HARNESS_PLAN_DIR/test-followups.md` (a flat list of seed entries shaped like Phase 2 drafts in `/z-test`). On the next `/z-plan` + `/z-test` cycle (or if the user re-runs `/z-test` on this same slug after seeding follow-up production tasks), these become mandatory TESTS.md entries. Closes the post-mortem loop automatically — the next plan run cannot ship without the regression test the post-mortem flagged.
- "Just record and move on" → leave the Post-mortem section as a standalone record.

Push-notify: "Post-mortem ready: `$Z_HARNESS_PLAN_DIR/DEBUG.md` Post-mortem section. Action items: <N> (converted to tasks: <yes/no>)."

## Phase 10 — Finalize

**Clear the notify-dedup session file** (once per top-level `/z-debug` invocation — ensures each fresh debug session gets its own notify de-dup state):
```bash
[[ -n "${Z_HARNESS_PLAN_DIR:-}" ]] && rm -f "$Z_HARNESS_PLAN_DIR/.notify-dedup-session"
```

Set run-brief env and host sections **before** the shared fragment (classify may be `unknown` until `debug_run_end`):

```bash
CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="$Z_HARNESS_PLAN_DIR/DEBUG.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS=""
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"
```

### Branch: `status: shipped` (fix was applied and post-mortem written)

```bash
bash "$RB_SH" set-section --run "$RUN" --section outcome \
  --value "Debug complete. Root cause: ${ROOT_CAUSE_LINE}. Fix shipped; ${N_ACTIONS} post-mortem action item(s)."
bash "$RB_SH" set-section --run "$RUN" --section status --value "shipped"
NEXT_JSON_FILE="$(mktemp -t z-rb-next.XXXXXX.json)"
if [[ "$N_ACTIONS" -gt 0 ]]; then
  printf '%s\n' '{"label":"Review DEBUG.md action items","command":null}' > "$NEXT_JSON_FILE"
else
  printf '%s\n' '{"label":"Done — no follow-up required","command":null}' > "$NEXT_JSON_FILE"
fi
bash "$RB_SH" set-section --run "$RUN" --section next --json "$NEXT_JSON_FILE"
rm -f "$NEXT_JSON_FILE"
```

<!-- RUN-BRIEF-FINALIZE: shared finalize block — included via `<!-- include: commands/_fragments/run-brief-finalize.md -->` in registry commands; `/z-export` inlines this body (T007). -->

## Run Brief finalize (shared fragment)

Emit the terminal **Run Brief** before `deregister` / `*_run_end`. Chat and push text are **renders only** — never author completion prose independently; always render from `run-brief.json`.

**Prerequisite:** `run-brief.sh init` ran earlier in this command (after the registry `init_after` anchor). `$CURRENT_ARCHIVE_DIR/run-brief.json` must exist before this block runs.

### Placeholders (set by the host command before including this fragment)

| Placeholder | Meaning |
|-------------|---------|
| `$RUN` | Run id (same value passed to `log-event.sh` and `run-brief.sh --run`) |
| `$CURRENT_ARCHIVE_DIR` | Absolute path to `archive/$RUN/` for this command |
| `$RUN_BRIEF_ARTIFACT` | Primary artifact for approach/outcome derivation (absolute or plan-relative path). May be empty on early halt. |
| `$RUN_BRIEF_PROFILE` | `full` or `lite` — must match the profile passed to `init` (see `docs/llm/run-brief-registry.json`). `/z-do` uses `lite`; all other v1 registry commands use `full`. |
| `$RUN_BRIEF_ARTIFACT_FALLBACKS` | Optional colon-separated fallback paths (same `$RUN` expansion rules as `run-brief.sh`). Example: `PLAN.md:SPEC.md`. Exported before finalize; consumed by `run-brief.sh finalize` via `RUN_BRIEF_ARTIFACT_FALLBACKS` env. |

Host commands also export artifact env for finalize resolution:

```bash
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
```

---

### Finalize sequence (mandatory order)

Run these steps **in order** at the command's registry `finalize` anchor (before `deregister` and before replacing any legacy "Brief summary" prose).

#### 1. Aggregate decisions → `run-brief.json`

For **`$RUN_BRIEF_PROFILE=full`** only: if `decisions` is empty or absent, aggregate from `$CURRENT_ARCHIVE_DIR/events.jsonl` and append via `run-brief.sh append-decision` (last wins per `question_id`). Skip when `decisions` already has rows (orchestrator may have appended mid-run).

```bash
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"
BRIEF="$CURRENT_ARCHIVE_DIR/run-brief.json"
EVENTS="$CURRENT_ARCHIVE_DIR/events.jsonl"

PROFILE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("profile",""))' "$BRIEF")"
DEC_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("decisions") or []))' "$BRIEF")"

if [[ "$PROFILE" == "full" && "$DEC_COUNT" -eq 0 && -f "$EVENTS" ]]; then
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    QID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["question_id"])' "$row")"
    CHOSEN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["chosen"])' "$row")"
    WHY="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("why",""))' "$row")"
    SRC="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("source","event"))' "$row")"
    AD_ARGS=(--run "$RUN" --question-id "$QID" --chosen "$CHOSEN" --source "$SRC")
    [[ -n "$WHY" ]] && AD_ARGS+=(--why "$WHY")
    bash "$RB_SH" append-decision "${AD_ARGS[@]}"
  done < <(python3 - "$RB_PY" "$EVENTS" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("render_run_brief", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
for entry in mod.aggregate_decisions(sys.argv[2]):
    print(json.dumps(entry, ensure_ascii=False))
PY
)
fi
```

Event kinds aggregated: `user_choice`, `user_override`, `plan_route_decision`, `next_step_choice` (see `render-run-brief.py`).

#### 2. Derive from artifact / fallbacks

Resolve the first existing file in `$RUN_BRIEF_ARTIFACT` → `$RUN_BRIEF_ARTIFACT_FALLBACKS` (finalize re-resolves the same chain internally). When a file exists and profile is `full`, seed `approach` if still empty:

```bash
APPROACH_FILE=""
if [[ -n "$RUN_BRIEF_ARTIFACT" && -f "$RUN_BRIEF_ARTIFACT" ]]; then
  APPROACH_FILE="$RUN_BRIEF_ARTIFACT"
elif [[ -n "$RUN_BRIEF_ARTIFACT_FALLBACKS" ]]; then
  IFS=':' read -ra _RB_FB <<< "$RUN_BRIEF_ARTIFACT_FALLBACKS"
  for _cand in "${_RB_FB[@]}"; do
    [[ -z "$_cand" ]] && continue
    _expanded="${_cand//\$RUN/$RUN}"
    if [[ -f "$_expanded" ]]; then APPROACH_FILE="$_expanded"; break; fi
  done
fi

APPROACH_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("approach") or []))' "$BRIEF")"

if [[ "$RUN_BRIEF_PROFILE" == "full" && -n "$APPROACH_FILE" && "$APPROACH_COUNT" -eq 0 ]]; then
  _RB_EXTRACT_N="$(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rrb", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(len(mod.extract_approach_bullets(sys.argv[2])))
' "$RB_PY" "$APPROACH_FILE")"
  if [[ "$_RB_EXTRACT_N" -gt 0 ]]; then
    bash "$RB_SH" set-section --run "$RUN" --section approach --file "$APPROACH_FILE" || true
  fi
fi
```

Set **`outcome`** / **`next`** when the host command already knows them (recommended on halt paths before finalize):

```bash
# Example — host supplies halt outcome before including this fragment:
# bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
# bash "$RB_SH" set-section --run "$RUN" --section next --json /path/to/next.json
```

If `outcome` is still `Pending finalize`, `run-brief.sh finalize` fills it from `run-status.sh classify`.

#### 3. Finalize → validate JSON + emit `run_brief_end`

```bash
bash "$RB_SH" finalize --run "$RUN"
```

`finalize` classifies terminal status (via `run-status.sh` when unset), resolves artifact/fallback env, auto-downgrades to **lite** when no artifact exists on a full-profile brief (see halt-safe below), validates against `docs/llm/run-brief-contract.json`, and emits `run_brief_end`.

#### 3.5. Cost summary render → stdout (non-fatal, before chat)

```bash
COST_SUMMARY_TEXT=""
COST_RENDERER="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-cost-summary.py"
if [ -f "$COST_RENDERER" ] && [ -f "$CURRENT_ARCHIVE_DIR/events.jsonl" ]; then
  COST_SUMMARY_TEXT="$(python3 "$COST_RENDERER" "$CURRENT_ARCHIVE_DIR/events.jsonl" 2>/dev/null || true)"
fi
```

#### 4. Chat render → user (replaces hand-authored "Brief summary")

Print rendered chat text to the user — **do not** write independent summary prose:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format chat ${COST_SUMMARY_TEXT:+--cost-summary-text "$COST_SUMMARY_TEXT"}
```

#### 5. Push render (when notify policy allows)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ]; then
  PUSH_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  PushNotification("$PUSH_BODY")
fi
```

Push format: `{intent[:80]} · {outcome[:60]} · Next: {next.label}` (from JSON).

#### 5.5. Discord render (when notify policy + webhook URL allow)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end --channel discord)" = yes ]; then
  DISCORD_TITLE="${RUN_BRIEF_INTENT:-z-harness run}"
  DISCORD_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/notify-discord.sh" "$DISCORD_TITLE" "$DISCORD_BODY" || true
fi
```

Discord uses enriched embed format — includes cost summary when available (not identical to PushNotification content). Non-fatal on failure.

#### 6. Hard gate — `--require` before deregister

Run **after** chat/push renders, **before** `active-plan-registry.py deregister` or any terminal `FINALIZE_STATUS` handoff:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --require
RB_REQUIRE_RC=$?
if [[ "$RB_REQUIRE_RC" -ne 0 ]]; then
  echo "run-brief: --require failed (missing or invalid run-brief.json)" >&2
  FINALIZE_STATUS=aborted
  # Do not deregister as complete — fix brief or abort run
fi
```

On `--require` failure: set `FINALIZE_STATUS=aborted` and do not deregister with `complete`.

---

### Halt-safe: missing artifact → lite brief

Early halt / abort paths often have **no** primary artifact (`FIX.md`, `REPORT.md`, `approach.md`, …). The brief is still **required** before deregister, but may be **lite** (Intent + Outcome + Next only — `approach` and `decisions` keys omitted).

| Condition | Behavior |
|-----------|----------|
| `$RUN_BRIEF_PROFILE=full` and no artifact/fallback file exists at finalize | `run-brief.sh finalize` auto-downgrades to `profile: lite`, drops `approach`/`decisions` **only on halt/aborted paths** — never when status is `complete` or `shipped` |
| `${FINALIZE_STATUS:-}` is `aborted` or classify → `halted` | Ensure `intent` (from init) + `outcome` (set-section or finalize default `"Halted before completion"`) + `next`; lite profile is valid |
| `render-run-brief.py --require` on lite brief | Passes when intent, outcome, next validate — **does not** require approach/decisions |

**Host command responsibilities on halt:**

1. Still include this fragment before deregister (unless the command is on the registry `skip_brief_on` list, e.g. `/z-implement-all` `compaction_pause` only).
2. Set a concrete `outcome` when possible: `bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"`.
3. Do not treat missing artifact as skip-brief — finalize produces lite JSON instead.

---

### Invariants

1. Chat and push text are always rendered from `run-brief.json` — never independently authored at finalize.
2. `--require` runs on every terminal exit that includes this fragment (complete, halted, aborted) before deregister.
3. Empty `decisions: []` is valid for full profile when no decision events occurred.
4. `/z-stats` is not auto-invoked here.
5. Optional debug mirror: `Z_HARNESS_RUN_BRIEF_DEBUG=1` writes `run-brief.md` beside JSON (see `run-brief.sh finalize`).

Log (after brief `--require` gate):
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" debug_run_end \
  "$(printf '{"command":"z-debug","status":"shipped","hypothesis_cycles":%d,"total_hypotheses_generated":%d,"action_items":%d,"postmortem_written":true}' "$CYCLES" "$N_HYPOTHESES" "$N_ACTIONS")"
```

**Memory review:** After logging `debug_run_end` with `status: shipped`, invoke `bash scripts/run-memory-review.sh "$RUN" "debug"` and parse its stdout with `mapfile`. On `STATUS: skipped`, the helper has already emitted the terminal event; honor the D11 push-notify policy (push-notify once per `(slug, skip_reason)` for `skipped_broken_context` states, deduped via `.notify-dedup-session`). On `STATUS: ready`, dispatch the review-agent with `parent_command: debug`, `debug_md_path` from line 5 (the path to DEBUG.md), `spec_path` from line 3 (may be empty), `cumulative_diff_path` from line 2, and `tags_path` from line 4. Run the sequential AskUserQuestion loop (hard cap 3 candidates) with source `incident:debug-<slug>-<RUN>`. Emit exactly one `memory_review_terminal` event per invocation: the helper emits it on skip paths; the orchestrator emits it after the user-gate loop for `ran_empty` and `needs_user` paths. See `skills/z-debug/SKILL.md` Phase 10 for the full step-by-step procedure.

**Deregister this run** (best-effort, non-fatal). Per the FINALIZE_STATUS rule: normal completion deregisters with `complete` only when brief `--require` passed.
```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
  --run-id "$RUN" --status "${FINALIZE_STATUS:-complete}" || true   # CLI self-logs registry_error on failure
```

### Branch: `status: abandoned` (debug was inconclusive — no fix shipped)

```bash
bash "$RB_SH" set-section --run "$RUN" --section outcome \
  --value "Debug inconclusive after ${CYCLES} hypothesis cycle(s); no fix shipped."
bash "$RB_SH" set-section --run "$RUN" --section status --value "aborted"
bash "$RB_SH" set-section --run "$RUN" --section next --json /dev/stdin <<'JSON'
{"label": "Retry /z-debug or escalate via /z-plan", "command": null}
JSON
```

<!-- RUN-BRIEF-FINALIZE: shared finalize block — included via `<!-- include: commands/_fragments/run-brief-finalize.md -->` in registry commands; `/z-export` inlines this body (T007). -->

## Run Brief finalize (shared fragment)

Emit the terminal **Run Brief** before `deregister` / `*_run_end`. Chat and push text are **renders only** — never author completion prose independently; always render from `run-brief.json`.

**Prerequisite:** `run-brief.sh init` ran earlier in this command (after the registry `init_after` anchor). `$CURRENT_ARCHIVE_DIR/run-brief.json` must exist before this block runs.

### Placeholders (set by the host command before including this fragment)

| Placeholder | Meaning |
|-------------|---------|
| `$RUN` | Run id (same value passed to `log-event.sh` and `run-brief.sh --run`) |
| `$CURRENT_ARCHIVE_DIR` | Absolute path to `archive/$RUN/` for this command |
| `$RUN_BRIEF_ARTIFACT` | Primary artifact for approach/outcome derivation (absolute or plan-relative path). May be empty on early halt. |
| `$RUN_BRIEF_PROFILE` | `full` or `lite` — must match the profile passed to `init` (see `docs/llm/run-brief-registry.json`). `/z-do` uses `lite`; all other v1 registry commands use `full`. |
| `$RUN_BRIEF_ARTIFACT_FALLBACKS` | Optional colon-separated fallback paths (same `$RUN` expansion rules as `run-brief.sh`). Example: `PLAN.md:SPEC.md`. Exported before finalize; consumed by `run-brief.sh finalize` via `RUN_BRIEF_ARTIFACT_FALLBACKS` env. |

Host commands also export artifact env for finalize resolution:

```bash
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
```

---

### Finalize sequence (mandatory order)

Run these steps **in order** at the command's registry `finalize` anchor (before `deregister` and before replacing any legacy "Brief summary" prose).

#### 1. Aggregate decisions → `run-brief.json`

For **`$RUN_BRIEF_PROFILE=full`** only: if `decisions` is empty or absent, aggregate from `$CURRENT_ARCHIVE_DIR/events.jsonl` and append via `run-brief.sh append-decision` (last wins per `question_id`). Skip when `decisions` already has rows (orchestrator may have appended mid-run).

```bash
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"
BRIEF="$CURRENT_ARCHIVE_DIR/run-brief.json"
EVENTS="$CURRENT_ARCHIVE_DIR/events.jsonl"

PROFILE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("profile",""))' "$BRIEF")"
DEC_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("decisions") or []))' "$BRIEF")"

if [[ "$PROFILE" == "full" && "$DEC_COUNT" -eq 0 && -f "$EVENTS" ]]; then
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    QID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["question_id"])' "$row")"
    CHOSEN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["chosen"])' "$row")"
    WHY="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("why",""))' "$row")"
    SRC="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("source","event"))' "$row")"
    AD_ARGS=(--run "$RUN" --question-id "$QID" --chosen "$CHOSEN" --source "$SRC")
    [[ -n "$WHY" ]] && AD_ARGS+=(--why "$WHY")
    bash "$RB_SH" append-decision "${AD_ARGS[@]}"
  done < <(python3 - "$RB_PY" "$EVENTS" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("render_run_brief", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
for entry in mod.aggregate_decisions(sys.argv[2]):
    print(json.dumps(entry, ensure_ascii=False))
PY
)
fi
```

Event kinds aggregated: `user_choice`, `user_override`, `plan_route_decision`, `next_step_choice` (see `render-run-brief.py`).

#### 2. Derive from artifact / fallbacks

Resolve the first existing file in `$RUN_BRIEF_ARTIFACT` → `$RUN_BRIEF_ARTIFACT_FALLBACKS` (finalize re-resolves the same chain internally). When a file exists and profile is `full`, seed `approach` if still empty:

```bash
APPROACH_FILE=""
if [[ -n "$RUN_BRIEF_ARTIFACT" && -f "$RUN_BRIEF_ARTIFACT" ]]; then
  APPROACH_FILE="$RUN_BRIEF_ARTIFACT"
elif [[ -n "$RUN_BRIEF_ARTIFACT_FALLBACKS" ]]; then
  IFS=':' read -ra _RB_FB <<< "$RUN_BRIEF_ARTIFACT_FALLBACKS"
  for _cand in "${_RB_FB[@]}"; do
    [[ -z "$_cand" ]] && continue
    _expanded="${_cand//\$RUN/$RUN}"
    if [[ -f "$_expanded" ]]; then APPROACH_FILE="$_expanded"; break; fi
  done
fi

APPROACH_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("approach") or []))' "$BRIEF")"

if [[ "$RUN_BRIEF_PROFILE" == "full" && -n "$APPROACH_FILE" && "$APPROACH_COUNT" -eq 0 ]]; then
  _RB_EXTRACT_N="$(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rrb", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(len(mod.extract_approach_bullets(sys.argv[2])))
' "$RB_PY" "$APPROACH_FILE")"
  if [[ "$_RB_EXTRACT_N" -gt 0 ]]; then
    bash "$RB_SH" set-section --run "$RUN" --section approach --file "$APPROACH_FILE" || true
  fi
fi
```

Set **`outcome`** / **`next`** when the host command already knows them (recommended on halt paths before finalize):

```bash
# Example — host supplies halt outcome before including this fragment:
# bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
# bash "$RB_SH" set-section --run "$RUN" --section next --json /path/to/next.json
```

If `outcome` is still `Pending finalize`, `run-brief.sh finalize` fills it from `run-status.sh classify`.

#### 3. Finalize → validate JSON + emit `run_brief_end`

```bash
bash "$RB_SH" finalize --run "$RUN"
```

`finalize` classifies terminal status (via `run-status.sh` when unset), resolves artifact/fallback env, auto-downgrades to **lite** when no artifact exists on a full-profile brief (see halt-safe below), validates against `docs/llm/run-brief-contract.json`, and emits `run_brief_end`.

#### 3.5. Cost summary render → stdout (non-fatal, before chat)

```bash
COST_SUMMARY_TEXT=""
COST_RENDERER="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-cost-summary.py"
if [ -f "$COST_RENDERER" ] && [ -f "$CURRENT_ARCHIVE_DIR/events.jsonl" ]; then
  COST_SUMMARY_TEXT="$(python3 "$COST_RENDERER" "$CURRENT_ARCHIVE_DIR/events.jsonl" 2>/dev/null || true)"
fi
```

#### 4. Chat render → user (replaces hand-authored "Brief summary")

Print rendered chat text to the user — **do not** write independent summary prose:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format chat ${COST_SUMMARY_TEXT:+--cost-summary-text "$COST_SUMMARY_TEXT"}
```

#### 5. Push render (when notify policy allows)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ]; then
  PUSH_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  PushNotification("$PUSH_BODY")
fi
```

Push format: `{intent[:80]} · {outcome[:60]} · Next: {next.label}` (from JSON).

#### 5.5. Discord render (when notify policy + webhook URL allow)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end --channel discord)" = yes ]; then
  DISCORD_TITLE="${RUN_BRIEF_INTENT:-z-harness run}"
  DISCORD_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/notify-discord.sh" "$DISCORD_TITLE" "$DISCORD_BODY" || true
fi
```

Discord uses enriched embed format — includes cost summary when available (not identical to PushNotification content). Non-fatal on failure.

#### 6. Hard gate — `--require` before deregister

Run **after** chat/push renders, **before** `active-plan-registry.py deregister` or any terminal `FINALIZE_STATUS` handoff:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --require
RB_REQUIRE_RC=$?
if [[ "$RB_REQUIRE_RC" -ne 0 ]]; then
  echo "run-brief: --require failed (missing or invalid run-brief.json)" >&2
  FINALIZE_STATUS=aborted
  # Do not deregister as complete — fix brief or abort run
fi
```

On `--require` failure: set `FINALIZE_STATUS=aborted` and do not deregister with `complete`.

---

### Halt-safe: missing artifact → lite brief

Early halt / abort paths often have **no** primary artifact (`FIX.md`, `REPORT.md`, `approach.md`, …). The brief is still **required** before deregister, but may be **lite** (Intent + Outcome + Next only — `approach` and `decisions` keys omitted).

| Condition | Behavior |
|-----------|----------|
| `$RUN_BRIEF_PROFILE=full` and no artifact/fallback file exists at finalize | `run-brief.sh finalize` auto-downgrades to `profile: lite`, drops `approach`/`decisions` **only on halt/aborted paths** — never when status is `complete` or `shipped` |
| `${FINALIZE_STATUS:-}` is `aborted` or classify → `halted` | Ensure `intent` (from init) + `outcome` (set-section or finalize default `"Halted before completion"`) + `next`; lite profile is valid |
| `render-run-brief.py --require` on lite brief | Passes when intent, outcome, next validate — **does not** require approach/decisions |

**Host command responsibilities on halt:**

1. Still include this fragment before deregister (unless the command is on the registry `skip_brief_on` list, e.g. `/z-implement-all` `compaction_pause` only).
2. Set a concrete `outcome` when possible: `bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"`.
3. Do not treat missing artifact as skip-brief — finalize produces lite JSON instead.

---

### Invariants

1. Chat and push text are always rendered from `run-brief.json` — never independently authored at finalize.
2. `--require` runs on every terminal exit that includes this fragment (complete, halted, aborted) before deregister.
3. Empty `decisions: []` is valid for full profile when no decision events occurred.
4. `/z-stats` is not auto-invoked here.
5. Optional debug mirror: `Z_HARNESS_RUN_BRIEF_DEBUG=1` writes `run-brief.md` beside JSON (see `run-brief.sh finalize`).

Log (after brief `--require` gate):
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" debug_run_end \
  "$(printf '{"command":"z-debug","status":"abandoned","hypothesis_cycles":%d,"total_hypotheses_generated":%d}' "$CYCLES" "$N_HYPOTHESES")"
```

**Deregister this run** (best-effort, non-fatal):
```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
  --run-id "$RUN" --status "${FINALIZE_STATUS:-complete}" || true   # CLI self-logs registry_error on failure
```

Do NOT invoke `run-memory-review.sh` on the abandoned branch. No memory-review telemetry is emitted for inconclusive debug sessions.

## Run Brief — halt finalize

Before `deregister --status aborted` on any halt after `run-brief.sh init` (unless register failed — no deregister). Substitute `<reason>` in the outcome line. When `DEBUG.md` is missing, the shared fragment auto-downgrades to **lite** (Intent + Outcome + Next).

```bash
CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="$Z_HARNESS_PLAN_DIR/DEBUG.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS=""
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
bash "$RB_SH" set-section --run "$RUN" --section next --json /dev/stdin <<'JSON'
{"label": "Review debug status and retry or escalate", "command": null}
JSON
```

<!-- RUN-BRIEF-FINALIZE: shared finalize block — included via `<!-- include: commands/_fragments/run-brief-finalize.md -->` in registry commands; `/z-export` inlines this body (T007). -->

## Run Brief finalize (shared fragment)

Emit the terminal **Run Brief** before `deregister` / `*_run_end`. Chat and push text are **renders only** — never author completion prose independently; always render from `run-brief.json`.

**Prerequisite:** `run-brief.sh init` ran earlier in this command (after the registry `init_after` anchor). `$CURRENT_ARCHIVE_DIR/run-brief.json` must exist before this block runs.

### Placeholders (set by the host command before including this fragment)

| Placeholder | Meaning |
|-------------|---------|
| `$RUN` | Run id (same value passed to `log-event.sh` and `run-brief.sh --run`) |
| `$CURRENT_ARCHIVE_DIR` | Absolute path to `archive/$RUN/` for this command |
| `$RUN_BRIEF_ARTIFACT` | Primary artifact for approach/outcome derivation (absolute or plan-relative path). May be empty on early halt. |
| `$RUN_BRIEF_PROFILE` | `full` or `lite` — must match the profile passed to `init` (see `docs/llm/run-brief-registry.json`). `/z-do` uses `lite`; all other v1 registry commands use `full`. |
| `$RUN_BRIEF_ARTIFACT_FALLBACKS` | Optional colon-separated fallback paths (same `$RUN` expansion rules as `run-brief.sh`). Example: `PLAN.md:SPEC.md`. Exported before finalize; consumed by `run-brief.sh finalize` via `RUN_BRIEF_ARTIFACT_FALLBACKS` env. |

Host commands also export artifact env for finalize resolution:

```bash
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
```

---

### Finalize sequence (mandatory order)

Run these steps **in order** at the command's registry `finalize` anchor (before `deregister` and before replacing any legacy "Brief summary" prose).

#### 1. Aggregate decisions → `run-brief.json`

For **`$RUN_BRIEF_PROFILE=full`** only: if `decisions` is empty or absent, aggregate from `$CURRENT_ARCHIVE_DIR/events.jsonl` and append via `run-brief.sh append-decision` (last wins per `question_id`). Skip when `decisions` already has rows (orchestrator may have appended mid-run).

```bash
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"
BRIEF="$CURRENT_ARCHIVE_DIR/run-brief.json"
EVENTS="$CURRENT_ARCHIVE_DIR/events.jsonl"

PROFILE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("profile",""))' "$BRIEF")"
DEC_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("decisions") or []))' "$BRIEF")"

if [[ "$PROFILE" == "full" && "$DEC_COUNT" -eq 0 && -f "$EVENTS" ]]; then
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    QID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["question_id"])' "$row")"
    CHOSEN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["chosen"])' "$row")"
    WHY="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("why",""))' "$row")"
    SRC="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("source","event"))' "$row")"
    AD_ARGS=(--run "$RUN" --question-id "$QID" --chosen "$CHOSEN" --source "$SRC")
    [[ -n "$WHY" ]] && AD_ARGS+=(--why "$WHY")
    bash "$RB_SH" append-decision "${AD_ARGS[@]}"
  done < <(python3 - "$RB_PY" "$EVENTS" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("render_run_brief", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
for entry in mod.aggregate_decisions(sys.argv[2]):
    print(json.dumps(entry, ensure_ascii=False))
PY
)
fi
```

Event kinds aggregated: `user_choice`, `user_override`, `plan_route_decision`, `next_step_choice` (see `render-run-brief.py`).

#### 2. Derive from artifact / fallbacks

Resolve the first existing file in `$RUN_BRIEF_ARTIFACT` → `$RUN_BRIEF_ARTIFACT_FALLBACKS` (finalize re-resolves the same chain internally). When a file exists and profile is `full`, seed `approach` if still empty:

```bash
APPROACH_FILE=""
if [[ -n "$RUN_BRIEF_ARTIFACT" && -f "$RUN_BRIEF_ARTIFACT" ]]; then
  APPROACH_FILE="$RUN_BRIEF_ARTIFACT"
elif [[ -n "$RUN_BRIEF_ARTIFACT_FALLBACKS" ]]; then
  IFS=':' read -ra _RB_FB <<< "$RUN_BRIEF_ARTIFACT_FALLBACKS"
  for _cand in "${_RB_FB[@]}"; do
    [[ -z "$_cand" ]] && continue
    _expanded="${_cand//\$RUN/$RUN}"
    if [[ -f "$_expanded" ]]; then APPROACH_FILE="$_expanded"; break; fi
  done
fi

APPROACH_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("approach") or []))' "$BRIEF")"

if [[ "$RUN_BRIEF_PROFILE" == "full" && -n "$APPROACH_FILE" && "$APPROACH_COUNT" -eq 0 ]]; then
  _RB_EXTRACT_N="$(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rrb", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(len(mod.extract_approach_bullets(sys.argv[2])))
' "$RB_PY" "$APPROACH_FILE")"
  if [[ "$_RB_EXTRACT_N" -gt 0 ]]; then
    bash "$RB_SH" set-section --run "$RUN" --section approach --file "$APPROACH_FILE" || true
  fi
fi
```

Set **`outcome`** / **`next`** when the host command already knows them (recommended on halt paths before finalize):

```bash
# Example — host supplies halt outcome before including this fragment:
# bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
# bash "$RB_SH" set-section --run "$RUN" --section next --json /path/to/next.json
```

If `outcome` is still `Pending finalize`, `run-brief.sh finalize` fills it from `run-status.sh classify`.

#### 3. Finalize → validate JSON + emit `run_brief_end`

```bash
bash "$RB_SH" finalize --run "$RUN"
```

`finalize` classifies terminal status (via `run-status.sh` when unset), resolves artifact/fallback env, auto-downgrades to **lite** when no artifact exists on a full-profile brief (see halt-safe below), validates against `docs/llm/run-brief-contract.json`, and emits `run_brief_end`.

#### 3.5. Cost summary render → stdout (non-fatal, before chat)

```bash
COST_SUMMARY_TEXT=""
COST_RENDERER="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-cost-summary.py"
if [ -f "$COST_RENDERER" ] && [ -f "$CURRENT_ARCHIVE_DIR/events.jsonl" ]; then
  COST_SUMMARY_TEXT="$(python3 "$COST_RENDERER" "$CURRENT_ARCHIVE_DIR/events.jsonl" 2>/dev/null || true)"
fi
```

#### 4. Chat render → user (replaces hand-authored "Brief summary")

Print rendered chat text to the user — **do not** write independent summary prose:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format chat ${COST_SUMMARY_TEXT:+--cost-summary-text "$COST_SUMMARY_TEXT"}
```

#### 5. Push render (when notify policy allows)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ]; then
  PUSH_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  PushNotification("$PUSH_BODY")
fi
```

Push format: `{intent[:80]} · {outcome[:60]} · Next: {next.label}` (from JSON).

#### 5.5. Discord render (when notify policy + webhook URL allow)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end --channel discord)" = yes ]; then
  DISCORD_TITLE="${RUN_BRIEF_INTENT:-z-harness run}"
  DISCORD_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/notify-discord.sh" "$DISCORD_TITLE" "$DISCORD_BODY" || true
fi
```

Discord uses enriched embed format — includes cost summary when available (not identical to PushNotification content). Non-fatal on failure.

#### 6. Hard gate — `--require` before deregister

Run **after** chat/push renders, **before** `active-plan-registry.py deregister` or any terminal `FINALIZE_STATUS` handoff:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --require
RB_REQUIRE_RC=$?
if [[ "$RB_REQUIRE_RC" -ne 0 ]]; then
  echo "run-brief: --require failed (missing or invalid run-brief.json)" >&2
  FINALIZE_STATUS=aborted
  # Do not deregister as complete — fix brief or abort run
fi
```

On `--require` failure: set `FINALIZE_STATUS=aborted` and do not deregister with `complete`.

---

### Halt-safe: missing artifact → lite brief

Early halt / abort paths often have **no** primary artifact (`FIX.md`, `REPORT.md`, `approach.md`, …). The brief is still **required** before deregister, but may be **lite** (Intent + Outcome + Next only — `approach` and `decisions` keys omitted).

| Condition | Behavior |
|-----------|----------|
| `$RUN_BRIEF_PROFILE=full` and no artifact/fallback file exists at finalize | `run-brief.sh finalize` auto-downgrades to `profile: lite`, drops `approach`/`decisions` **only on halt/aborted paths** — never when status is `complete` or `shipped` |
| `${FINALIZE_STATUS:-}` is `aborted` or classify → `halted` | Ensure `intent` (from init) + `outcome` (set-section or finalize default `"Halted before completion"`) + `next`; lite profile is valid |
| `render-run-brief.py --require` on lite brief | Passes when intent, outcome, next validate — **does not** require approach/decisions |

**Host command responsibilities on halt:**

1. Still include this fragment before deregister (unless the command is on the registry `skip_brief_on` list, e.g. `/z-implement-all` `compaction_pause` only).
2. Set a concrete `outcome` when possible: `bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"`.
3. Do not treat missing artifact as skip-brief — finalize produces lite JSON instead.

---

### Invariants

1. Chat and push text are always rendered from `run-brief.json` — never independently authored at finalize.
2. `--require` runs on every terminal exit that includes this fragment (complete, halted, aborted) before deregister.
3. Empty `decisions: []` is valid for full profile when no decision events occurred.
4. `/z-stats` is not auto-invoked here.
5. Optional debug mirror: `Z_HARNESS_RUN_BRIEF_DEBUG=1` writes `run-brief.md` beside JSON (see `run-brief.sh finalize`).

```bash
FINALIZE_STATUS=aborted
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
  --run-id "$RUN" --status aborted 2>/dev/null || true
```

## Artifacts produced

- `$Z_HARNESS_PLAN_DIR/DEBUG.md` — single unified artifact with sections:
  ```
  # Debug: <slug>
  ## Problem
  ## Evidence Inventory
  ## Hypothesis Pool
  ## Test Matrix
  ## Experiment Log
  ## Score Updates
  ## Eliminated Alternatives
  ## Root Cause
  ## Fix Plan
  ## Verification
  ## Post-mortem
  ```
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/round1-orchestrator.md` — pre-dispatch checkpoint of the orchestrator's independent Round 1 hypotheses (contamination mitigation).
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/transcripts/` — consultant transcripts.
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/bisect.log` + `offending-show.txt` + `offending-diff.patch` — Phase 2.5 bisect artifacts (only if Phase 2.5 ran and returned `ok`).
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/diff.patch` — fix diff.
- `$Z_HARNESS_PLAN_DIR/MR-REVIEW.md` — optional, if user opted into MR-style review in Phase 9.

## Phase-visibility matrix (consultant context discipline)

Source of truth for what each subagent dispatch sees. Subagent prompts must never include sections outside the listed scope, and must never receive likelihood buckets or posteriors except where listed.

| Phase | Consultant call | Sections passed | Forbidden | Raw test output? |
|---|---|---|---|---|
| 2.5 (bisect) | bisect-isolator (Haiku, not a consultant) | repro_command, good_ref, bad_ref, repo_root, task_id | likelihood buckets, posteriors, any hypothesis content | N/A — mechanical only |
| 3a (Round 1) | both, MODE `generate-hypotheses-round1` | Problem; Evidence Inventory (incl. bisect EVID if Phase 2.5 produced one); doc-fetcher synthesis; bisect result block if Phase 2.5 returned `ok` | Hypothesis Pool (doesn't exist yet); any orchestrator-internal block; likelihood buckets | No |
| 3b (Round 2) | both, MODE `generate-hypotheses-round2-adversarial` | Problem; Evidence Inventory; Hypothesis Pool (full) | Test Matrix; Experiment Log; Score Updates | No |
| 6 (optional Round 3) | both, MODE `generate-hypotheses-round1` | Problem; Evidence Inventory; eliminated `claim` text + falsifying `discriminating_test` only | priors, likelihoods, posteriors, full Eliminated Alternatives section | No |
| 7 (fix consult) | both, MODE `light-fix` | Problem; Evidence Inventory; winning Hypothesis Pool rows; Experiment Log; draft Root Cause; draft Evidence coverage table | Eliminated Alternatives; Score Updates history | No |

Orchestrator alone reads raw test output and assigns likelihood buckets (Phase 6, step 2). This row never appears in the table.

## Hard rules

- **Never debug without repro.** If repro is impossible and user picks "proceed on inference," document that decision in the Problem section and flag in the Post-mortem Confidence section.
- **Never skip the post-mortem.** Even on a trivial bug — the preventative action-items habit is what makes `/z-debug` different from `/z-fix`.
- **Never skip Codex review on the fix** — the safety gate is non-negotiable.
- **Always emit BOTH Round 1 and Round 2 hypothesis-generation consults** — when `experiment.persona_rotation=true`: ten subagent calls total during generation (5 in R1 + 5 in R2), plus five more in Phase 7 for the fix consult; when `experiment.persona_rotation=false`: four subagent calls total (2 in R1 + 2 in R2), plus two more in Phase 7. Persona prefixes (when `personas.critique_panel=true`) are drawn once before Phase 3a and reused at Phase 3b — the same draw populates both rounds.
- **Likelihood-bucket assignment is orchestrator-only.** Never delegate the `{strongly_falsified, …, strongly_supported}` call to a consultant. Never pass raw test output to a consultant.
- **Orchestrator's Round 1 block MUST be checkpointed to disk** (`archive/<run>/round1-orchestrator.md`) BEFORE consultant dispatch. Re-read from disk at merge time, not from conversation state.
- **Wrong-tool gate (Phase 0) is non-skippable.** If the user already has a hypothesis, exit with a `/z-fix` recommendation — do not proceed.
- **Never proceed past auto-bail thresholds** without explicit user override.
- **Fix-gate is objective and binary.** Opens only when (a) winning hypothesis posterior == `very_high` AND (b) every `EVID-NNN` in the Evidence coverage table has status ∈ `{explained, falsifies_alternative, orthogonal_with_reason}` (zero `unexplained`).
- **Phase 2.5 bisect is fast-path-only.** Bisect never blocks the pipeline, never replaces the hypothesis tournament, and never pre-fills the winning hypothesis. It augments the Evidence Inventory and seeds Phase 3a; the fix-gate still requires full posterior + evidence-coverage convergence.
- **No emojis** anywhere in artifacts.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
| `ask_user` | yes | Empty arguments gate; Setup slug confirmation; Phase 0 wrong-tool gate; Phase 1 problem clarification; Phase 2 cannot-reproduce gate; Phase 6 hard cycle cap gate; Phase 7 fix approval; Phase 9 MR-review gate; Phase 9 action-item disposition |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
