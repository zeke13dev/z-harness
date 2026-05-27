---
description: Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md.
role: workflow
---

You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.

This command is **read-only**. Never edit active codebase files. Plan adjustments happen later via `/z-amend` or `/z-plan` based on the audit report's findings.

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.

Use only already-known setup signals: `has_existing_plan`, `candidate_files`, `expected_tasks`, `docs_stale_or_drifted`, and whether `SPEC.md`, `PLAN.md`, and `TASKS.md` are present under `$Z_HARNESS_PLAN_DIR`.

Deterministic routes:
- If no plan artifacts are found, route to `/z-plan`; do not pretend an audit can proceed.
- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
- If the completed audit finds accepted plan changes, route contextually to `/z-amend`.
- If doc drift blocks audit confidence, route contextually to `/z-maintain-docs`.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

---

## Phase 0 — Setup

0. **Initialize no-plan route archive:**
   Before discovering a plan slug, define a route archive for the "no artifacts found" branch:
   ```bash
   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
   ```
1. **Discover plan slug:**
   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
   - If single candidate -> use it.
   - If multiple candidates -> use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
2. **Export variables:**
   Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`. Define `$BASE = $Z_HARNESS_PLAN_DIR`.
3. **Pick run ID:**
   `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>-audit-plan`
4. **Create directories:**
   `mkdir -p $BASE/archive/$RUN/transcripts`
5. **Version stamp + log run start:**
   Capture the z-harness plugin version stamp and log the run start:
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["slug"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "$Z_HARNESS_SLUG")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_start "$START_PAYLOAD"
   ```
6. **Notification policy:** see [docs/human/config.md](docs/human/config.md) (notify.level key).
7. **Docs Grounding:**
   If `docs/llm/INDEX.json` exists in the repo root, dispatch `doc-fetcher` (Haiku) to identify concepts touched by this plan:
   ```
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     subagent_type="doc-fetcher",
     description="Doc context for plan audit <slug>",
     prompt="query: which concepts cover <plan files and symbols>?\nrepo_root: <abs path>\ndepth: summary"
   )
   ```
   Use the returned concept slugs to retrieve the appropriate `docs/llm/<concept>.json` files as plan-grounding validation guidelines.

---

## Phase 1 — Reality Check (Reference Verification)

Parse `$BASE/SPEC.md` and `$BASE/TASKS.md` to identify factual claims made about the active codebase. Scrutinize these references:

1. **Entities to verify:**
   - **Files & Directories:** Ensure paths described as existing or as preconditions actually exist.
   - **Symbols:** Grep for declarations of functions, methods, classes, variables, or types mentioned in the spec.
   - **Configs:** Verify the existence of specific configuration files or specific JSON/YAML/TOML keys referenced in the plan.
   - **Database Elements:** Ensure tables or columns referenced as active database preconditions exist in schema declarations, models, or migration files.
   - **CLI Flags:** Ensure referenced CLI arguments are declared in their respective option-parsing functions.
2. **Bucket division:**
   - **MUST EXIST NOW:** Entities described as present. Run `Read`/`Grep`/`Glob` to verify their existence and declarations exactly.
   - **WILL BE CREATED:** Newly proposed files. Verify that their proposed paths do not clash with existing files in the codebase.
3. **Drift & Hallucination detection:**
   - Flag similar-but-different naming (e.g. `user_id` vs `uid`, or double-suffixes).
   - Flag contract mismatches between proposed specifications and current codebase structures.
   - Flag dependency order violations (e.g., plan relies on a database table that is not created in this or any prior completed plan).

Checkpoint: Write results to `$BASE/archive/$RUN/phase1-reality.md`.

---

## Phase 2 — Best Practices & Design Audit

Audit the plan's architectural, design, and styling choices against best engineering practices:

1. **Standards verification:**
   - **KISS & DRY:** Check for unnecessary complexity, premature abstractions, or code duplication planned across tasks.
   - **SOLID:** Ensure clean single-responsibility components and clear interface boundaries.
   - **Style:** Align proposed changes with `STYLE.md` rules (if it exists).
2. **Defensive Bloat & Over-engineering:**
   - Check if error handling is overly defensive, or if unnecessary abstractions are introduced where simple code would suffice.
3. **Performance & Resources:**
   - Detect potential N+1 database queries, excessive object allocations in loops, locking/deadlock risks, or poor Big-O complexity in algorithms.
4. **Security & Validation:**
   - Ensure all input validation boundaries, sanitization strategies, authentication/authorization checks, and data exposure patterns are secure.

Checkpoint: Write results to `$BASE/archive/$RUN/phase2-design.md`.

---

## Phase 3 — Adversarial Cross-LLM Review

Spawn two consultants in parallel to review the plan's artifacts (`SPEC.md`, `PLAN.md`, `TASKS.md`) and Phase 1/2 audit notes with a highly critical, adversarial mindset:

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-primary",
  description="Adversarial plan audit review (Gemini) for <slug>",
  prompt="MODE: plan-audit-review\n\nSPEC:\n<SPEC.md>\n\nPLAN:\n<PLAN.md>\n\nTASKS:\n<TASKS.md>\n\nReality Check Notes:\n<phase1-reality.md>\n\nDesign Audit Notes:\n<phase2-design.md>\n\nAct as a highly critical, adversarial 'Senior Nitpicker'. Find logic flaws, race conditions, edge cases, missing tests in acceptance criteria, security concerns, style drift, or over-engineering in the plan. Report findings with severity (BLOCKER / MAJOR / MINOR), location, and recommendations."
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-secondary",
  description="Adversarial plan audit review (Codex) for <slug>",
  prompt="MODE: plan-audit-review\n\n<same prompt>"
)
```

Both consultants return structured findings. Transcripts are archived under `$BASE/archive/$RUN/transcripts/`.

---

## Phase 4 — Merge and Synthesize Findings

1. **Aggregation:**
   Merge findings from Reality Check, Design Audit, and both adversarial consultant reviews.
2. **One-Reason-This-Might-Be-Wrong Gate:**
   For every finding, write a brief statement detailing "one reason this finding might be wrong, irrelevant, or pedantic". If the pushback is valid:
   - Drop the finding from the final report.
   - Or demote its severity.
3. **Write final report:**
   Write the unified plan-audit report to `$BASE/PLAN_AUDIT_REPORT.md` (and save a copy in `$BASE/archive/$RUN/PLAN_AUDIT_REPORT.md`):
   ```markdown
   # Plan Audit Report — <slug>
   
   - **Date (UTC):** YYYY-MM-DDTHH:MMZ
   - **Slug:** <slug>
   - **Run ID:** <RUN>
   
   ## Summary
   - <Actionable high-level takeaways>
   
   ## reality-check Reality Check findings
   <Stale references, naming drift, clashing paths>
   
   ## design-check Design & Style findings
   <SOLID/DRY violations, style drift, over-engineering, performance, security>
   
   ## adversarial Adversarial Consult findings
   <Logic gaps, race conditions, unhandled edge cases, missing tests in acceptance>
   
   ## Consensus vs Disagreement
   - consensus: <findings flagged by multiple layers>
   - outlier: <findings worth manual scrutiny>
   
   ## Actionable Recommendations
   <Categorized recommendations with recommended actions>
   ```

---

## Phase 5 — User Gate & Action

1. **Notify:**
   If notification policy ≠ `off`, send a `PushNotification`: "Plan audit complete: N findings surfaced."
2. **Present report:**
   Present the list of findings to the user, highlighting BLOCKER and MAJOR severities.
3. **Resolver pre-check — run before invoking `AskUserQuestion`:**

   ```bash
   # Capture exit code separately — do NOT silence stderr
   RESOLVED="$(python3 scripts/config.py resolve-question workflow.audit_to_amend)"
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

   - **`skip`:** Skip the `AskUserQuestion` and proceed as if the user picked `$DEFAULT`. Emit `askuser_skipped` event:
     ```bash
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" askuser_skipped \
       "$(printf '{"question_id":"workflow.audit_to_amend","source":"%s"}' "$SOURCE")"
     ```
   - **`prefill`:** Present the `AskUserQuestion` normally, pre-select `$DEFAULT` as the recommended option (append label suffix: ` (Recommended — your preference)`).
   - **`ask`:** Present the `AskUserQuestion` normally. If `$SOURCE == "conflict"`, add to the question header text: `(Note: config says <X>, memory says <Y> — your answer below will be offered as a conflict-resolution write target.)` After the user picks an answer, if that answer differs from both config and memory values, surface a one-shot follow-up `AskUserQuestion`: "Record your answer as the new preference? (config / memory:very_strong / memory:strong / no — keep both stored, ask again next time)". Caller writes to config or dispatches `/z-suggest-memory` accordingly.

   **Ask user via `AskUserQuestion`** (when resolver result is `prefill` or `ask`):
   - **Amend Plan (Run z-amend):** Trigger interactive plan amendment to address findings.
   - **Proceed as-is:** Acknowledge findings as acceptable tradeoffs and start implementation.
   - **Reject & Re-plan:** Discard current plan artifacts and rerun `/z-plan`.
4. **Log run end:**
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_end \
     "$(printf '{"status":"complete","findings":%d,"blockers":%d,"majors":%d}' "$N_FINDINGS" "$N_BLOCKERS" "$N_MAJORS")"
   ```

---

---

## Phase 9 — Elevation Proposer

After the user gate in Phase 5 resolves, run the preference elevation check:

```bash
PROPOSE_OUT="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/propose-prefs.py" --check z-audit-plan 2>/dev/null)"
```

If `$PROPOSE_OUT` is non-empty, parse it as JSON and surface a one-shot preference proposal:

```python
import json
proposal = json.loads(PROPOSE_OUT)
qid = proposal["question_id"]
val = proposal["proposed_value"]
n   = len(proposal["evidence"])
scope_rec = proposal["scope_recommendation"]
```

Emit `proposal_surfaced`:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" proposal_surfaced \
  "$(python3 -c '
import json, sys
print(json.dumps({"question_id": sys.argv[1], "proposed_value": sys.argv[2], "n_evidence": int(sys.argv[3]), "scope_recommendation": sys.argv[4]}))
' "$qid" "$val" "$n" "$scope_rec")"
```

Present a single `AskUserQuestion`:

> "You've done `<cmd_a> → z-amend` **N times** — add `<val>` as your preference for `<qid>`?"
>
> Options:
> - **config** — write to project config (or global if `scope_recommendation=global`)
> - **memory:very_strong** — store as a very-strong routing-preference memory entry
> - **memory:strong** — store as a strong routing-preference memory entry
> - **no** — suppress this prompt for 30 days

Branch on the user's choice:

**`config` branch:**
```bash
SCOPE_FLAG="--scope=project"
[ "$scope_rec" = "global" ] && SCOPE_FLAG="--scope=global"
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" set workflow.audit_to_amend amend $SCOPE_FLAG
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" proposal_accepted \
  "$(printf '{"question_id":"%s","via":"config","scope":"%s"}' "$qid" "$scope_rec")"
```

**`memory:very_strong` or `memory:strong` branch:**

Dispatch `/z-suggest-memory` with `--kind routing-preference`:
```
/z-suggest-memory --kind routing-preference \
  --question-id <qid> \
  --value <val> \
  --strength <very_strong|strong> \
  --scope <scope_recommendation>
```

Then emit:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" proposal_accepted \
  "$(printf '{"question_id":"%s","via":"memory","strength":"%s","scope":"%s"}' "$qid" "$strength" "$scope_rec")"
```

**`no` branch:**

Write suppression entry with 30-day expiry:
```python
import json, os, time
from pathlib import Path
suppress_path = Path(".z-harness") / ".propose-suppress"
suppress_path.parent.mkdir(parents=True, exist_ok=True)
data = {}
if suppress_path.exists():
    try:
        data = json.loads(suppress_path.read_text())
    except (json.JSONDecodeError, OSError):
        data = {}
expiry = time.time() + 30 * 86400
data[qid] = str(expiry)
suppress_path.write_text(json.dumps(data))
```

Then emit:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" proposal_rejected \
  "$(printf '{"question_id":"%s","suppressed_until_epoch":"%s"}' "$qid" "$expiry")"
```

If `$PROPOSE_OUT` is empty, skip this phase entirely — no question is asked.

---

## Operating Principles

- **Rigorous Verification:** Validate all facts before starting the implementation.
- **Push Back on Reviews:** Apply the "one reason it might be wrong" check to keep reports high-signal.
- **Strictly Read-Only:** Never modify the codebase during the audit.
- **Format Consistency:** No emojis, professional headers, clean Markdown structures.
