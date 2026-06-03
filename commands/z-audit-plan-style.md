---
description: Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) for the same kind of code-quality issues /z-mr-review finds on a diff — defensive bloat, premature abstraction, DRY/KISS/SOLID violations, over-engineering, STYLE.md drift — BEFORE any code is written. Emits PLAN_STYLE_AUDIT.md with BLOCKER/MAJOR/MINOR findings suitable for /z-amend.
argument-hint: "[--slug <slug>]"
runtime: c1
driver_features_required:
  - subagent
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-audit-plan-style`** — a multi-LLM code-quality audit of plan artifacts (SPEC.md, PLAN.md, TASKS.md), modelled on `/z-mr-review` but operating on a plan rather than a diff. The output is `PLAN_STYLE_AUDIT.md` under `$Z_HARNESS_PLAN_DIR/`, with findings ranked BLOCKER / MAJOR / MINOR and shaped for direct promotion into `/z-amend`.

This command is **read-only**. Never edit active codebase files or plan artifacts. Plan adjustments happen later via `/z-amend` based on the findings the user keeps.

## Finding promotion contract

`/z-audit-plan-style` is a producer of the plan-amendment promotion contract:

- The parsed reviewer JSON is the structured finding source.
- `PLAN_STYLE_AUDIT.md` is both the evidence summary and the promotion artifact: ranked findings are emitted as amendment-shaped blocks that the user can delete before applying survivors.
- The command uses BLOCKER / MAJOR / MINOR severities (consistent with the audit-plan family); every emitted block includes source severity, category, source-file citation (`SPEC.md` / `PLAN.md` / `TASKS.md` + line range), task ID when applicable, proposed-symbol when applicable, finding detail, recommendation, and STYLE.md or `file:line` citation.

`PLAN_STYLE_AUDIT.md` is intentionally separate from `PLAN_AUDIT_REPORT.md` (`/z-audit-plan`'s correctness report). Users apply survivors with `/z-amend --from z-harness/<SLUG>/PLAN_STYLE_AUDIT.md`.

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan-style` is not a front-door planning command; it is valid only when plan artifacts exist.

Use only already-known setup signals: `has_existing_plan`, `has_style_md`, `candidate_files`, `docs_stale_or_drifted`, and whether `SPEC.md`, `PLAN.md`, and `TASKS.md` are present under `$Z_HARNESS_PLAN_DIR`.

Deterministic routes:
- If no plan artifacts are found, route to `/z-plan`; do not pretend a plan-style audit can proceed.
- If `STYLE.md` is missing from the repo root, route to `/z-style-init` — there is no `--no-style` escape. This is a hard gate.
- If all plan artifacts and `STYLE.md` exist, stay in `/z-audit-plan-style` and audit read-only.
- If the completed audit finds accepted plan changes, route contextually to `/z-amend`.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate. Do not execute the next command automatically.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose.
<!-- PLAN_ROUTE_CHECK_END -->

---

## Phase 0 — Setup

0. **Initialize no-plan route archive:**
   Before discovering a plan slug, define a route archive for the "no artifacts found" branch:
   ```bash
   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-style-no-plan
   NO_PLAN_ARCHIVE_DIR="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" base_dir)/archive/$NO_PLAN_RUN"
   ```
1. **Discover plan slug:**
   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
   - If single candidate → use it.
   <!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the slug
        selection question via their native channel. Silent omission is forbidden. -->
   - If multiple candidates → use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
   - If zero → `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create a style audit without plan artifacts.
2. **Export variables:**
   Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`. Define `$BASE = $Z_HARNESS_PLAN_DIR`.
3. **STYLE.md hard gate:**
   ```bash
   REPO_ROOT="$(git rev-parse --show-toplevel)"
   STYLE_PATH="$REPO_ROOT/STYLE.md"
   if [ ! -f "$STYLE_PATH" ]; then
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "${RUN:-pre-init}" plan_style_missing_style_md \
       "$(printf '{"slug":"%s"}' "$Z_HARNESS_SLUG")"
     echo "Error: no STYLE.md found at the repo root ($REPO_ROOT). Run /z-style-init first. There is no --no-style escape." >&2
     exit 1
   fi
   ```
4. **Pick run ID:**
   `RUN=$(date -u +%Y%m%dT%H%M%SZ)-${Z_HARNESS_SLUG}-audit-plan-style`
5. **Create directories:**
   `mkdir -p $BASE/archive/$RUN/transcripts`
6. **Voice availability pre-check:**
   ```bash
   command -v codex >/dev/null 2>&1 && CODEX_AVAILABLE=true || CODEX_AVAILABLE=false
   command -v gemini >/dev/null 2>&1 && GEMINI_AVAILABLE=true || GEMINI_AVAILABLE=false
   VOICES_AVAILABLE="claude"
   [ "$CODEX_AVAILABLE" = "true" ] && VOICES_AVAILABLE="$VOICES_AVAILABLE,codex"
   [ "$GEMINI_AVAILABLE" = "true" ] && VOICES_AVAILABLE="$VOICES_AVAILABLE,gemini"
   ```
   If `VOICES_AVAILABLE` is only `claude`, warn the user and log a degraded event:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_style_voices_degraded \
     "$(printf '{"slug":"%s","voices_available":"%s"}' "$Z_HARNESS_SLUG" "$VOICES_AVAILABLE")"
   ```
7. **Archive any existing PLAN_STYLE_AUDIT.md:**
   ```bash
   EXISTING="$BASE/PLAN_STYLE_AUDIT.md"
   if [ -f "$EXISTING" ]; then
     N=1
     while [ -f "$BASE/archive/$RUN/PLAN_STYLE_AUDIT.md.previous-$N" ]; do
       N=$(( N + 1 ))
     done
     cp "$EXISTING" "$BASE/archive/$RUN/PLAN_STYLE_AUDIT.md.previous-$N"
   fi
   ```
8. **Version stamp + log run start:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   STYLE_MD_REVISION="$(git rev-parse HEAD:STYLE.md 2>/dev/null || echo 'unknown')"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1])
   v["slug"] = sys.argv[2]
   v["run_id"] = sys.argv[3]
   v["voices_available"] = sys.argv[4].split(",")
   v["style_md_revision"] = sys.argv[5]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "$Z_HARNESS_SLUG" "$RUN" "$VOICES_AVAILABLE" "$STYLE_MD_REVISION")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_style_run_start "$START_PAYLOAD"
   ```
9. **Notification policy:** see [docs/human/config.md](docs/human/config.md) (notify.level key).

---

## Phase 1 — Build the concatenated plan-artifacts input

The reviewer agent consumes a single file with all three plan artifacts concatenated and tagged with marker lines, so it can attribute findings back to the correct `source_file`.

```bash
ART="$BASE/archive/$RUN/plan_artifacts.md"
{
  echo "=== SPEC.md ==="
  cat "$BASE/SPEC.md"
  echo ""
  echo "=== PLAN.md ==="
  cat "$BASE/PLAN.md"
  echo ""
  echo "=== TASKS.md ==="
  cat "$BASE/TASKS.md"
} > "$ART"
```

If any of `SPEC.md`, `PLAN.md`, or `TASKS.md` is missing, refuse early with a clear message (the plan-discovery step in Phase 0 should already require all three, but defend in depth):

```bash
for f in SPEC.md PLAN.md TASKS.md; do
  if [ ! -f "$BASE/$f" ]; then
    echo "Error: $BASE/$f is missing. /z-audit-plan-style requires all three plan artifacts." >&2
    exit 1
  fi
done
```

---

## Phase 2 — Dismissal-signature extraction

Invoke `scripts/extract-dismissals.py` with `--filename PLAN_STYLE_AUDIT.md` to compute prior dismissal signatures specific to this command:

```bash
DISMISSED_PATH="$BASE/archive/$RUN/dismissed_signatures.json"
if ! python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/extract-dismissals.py" \
  "$BASE" \
  --filename PLAN_STYLE_AUDIT.md \
  --max-runs 10 \
  > "$DISMISSED_PATH" 2>/dev/null; then
  echo '{"signatures":[],"n_runs_scanned":0}' > "$DISMISSED_PATH"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_style_dismissal_extract_failed \
    "$(printf '{"slug":"%s"}' "$Z_HARNESS_SLUG")"
fi
```

Emit one `plan_style_finding_dismissed` event per dismissed signature:

```bash
python3 - <<'PYEOF'
import json, os, subprocess
slug = os.environ['Z_HARNESS_SLUG']
run_id = os.environ['RUN']
base = os.environ['BASE']
plugin_root = os.environ.get('ANTIGRAVITY_PLUGIN_ROOT') or os.environ.get('CLAUDE_PLUGIN_ROOT', '')
path = os.path.join(base, 'archive', run_id, 'dismissed_signatures.json')
with open(path) as f:
    data = json.load(f)
for sig in data.get('signatures', []):
    payload = json.dumps({
        'slug': slug,
        'category': sig.get('category', ''),
        'prior_run_id': sig.get('prior_run_id') or sig.get('run_id', ''),
    })
    subprocess.run([
        'bash',
        os.path.join(plugin_root, 'scripts/log-event.sh'),
        run_id,
        'plan_style_finding_dismissed',
        payload,
    ])
PYEOF
```

(Ensure `BASE` is exported before the heredoc: `export BASE RUN Z_HARNESS_SLUG`.)

---

## Phase 3 — Dispatch the plan-style-reviewer agent

Resolve absolute paths and dispatch the agent. The agent does its own multi-voice fanout internally — the orchestrator dispatches it exactly once.

```bash
ART_ABS="$REPO_ROOT/$ART"
DISMISSED_ABS="$REPO_ROOT/$DISMISSED_PATH"
SLUG_DIR_ABS="$REPO_ROOT/$BASE"
```

Dispatch:

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip the Agent() call. The command cannot
     proceed without subagent support. -->
Agent(
  subagent_type="plan-style-reviewer",
  model="sonnet",
  description="Plan-style review for <Z_HARNESS_SLUG>",
  prompt="slug: <Z_HARNESS_SLUG>
run_id: <RUN>
slug_dir: <SLUG_DIR_ABS>
plan_artifacts_path: <ART_ABS>
style_path: <STYLE_PATH>
dismissed_signatures_path: <DISMISSED_ABS>
voices_available: [<VOICES_AVAILABLE>]"
)
```

Capture the agent's full return text as `AGENT_RETURN`.

---

## Phase 4 — Parse agent return and write PLAN_STYLE_AUDIT.md

### Step 4a — Extract findings JSON

Parse `AGENT_RETURN` by locating the first fenced `json` block. Extract and parse its contents as JSON with schema `{"findings": [...], "voices_used": [...]}`.

If no valid JSON block is found, log `plan_style_all_voices_failed` and exit nonzero with:

```
Error: plan-style-reviewer agent returned no parseable findings JSON. The agent return was:
<AGENT_RETURN>
```

Set `ALL_FINDINGS` = the parsed findings list.

### Step 4b — Extract summary block

Parse the `## Summary` block from `AGENT_RETURN` (the section after the JSON block). Extract:
- `voices_succeeded` — list
- `voices_failed` — list
- `dismissal_pattern_matches` — integer

If parsing fails for any field, default to: `voices_succeeded=[claude]`, `voices_failed=[]`, `dismissal_pattern_matches=0`.

### Step 4c — Compute aggregates and assign IDs

In the snippet below, `findings` refers to `ALL_FINDINGS` from Step 4a — the deduplicated finding list parsed from the agent's fenced JSON block.

```python
import json as _json, os as _os
_archive_dir = _os.environ['BASE'] + '/archive/' + _os.environ['RUN']
findings = ALL_FINDINGS  # bind for readability
total_findings = len(findings)
by_severity = {"BLOCKER": 0, "MAJOR": 0, "MINOR": 0}
by_category = {}
for f in findings:
    by_severity[f["severity"]] += 1
    cat = f.get("category", "uncategorized")
    by_category[cat] = by_category.get(cat, 0) + 1

with open(f"{_archive_dir}/by_severity.json", "w") as _fh:
    _fh.write(_json.dumps(by_severity))
with open(f"{_archive_dir}/by_category.json", "w") as _fh:
    _fh.write(_json.dumps(by_category))

severity_order = ["BLOCKER", "MAJOR", "MINOR"]
by_severity_label = {
    "BLOCKER": "would cause future bugs or maintenance pain",
    "MAJOR":   "clear quality regression vs the rest of the codebase",
    "MINOR":   "design hygiene",
}
```

Assign T-PS-NNN IDs by iterating findings in severity order (BLOCKER first, then MAJOR, then MINOR), then in original finding order within each severity group. IDs start at T-PS-001.

### Step 4d — Build findings_index

For each finding (in T-PS-NNN order), build a YAML findings_index entry:

```yaml
  - {id: T-PS-001, severity: BLOCKER, category: premature-abstraction, source_file: PLAN.md, title: "Short title"}
```

### Step 4e — Write PLAN_STYLE_AUDIT.md

Build the full content using this structure:

```markdown
---
artifact: plan-style-audit
slug: <SLUG>
run_id: <RUN>
generated_at: <ISO timestamp — date -u +%Y-%m-%dT%H:%M:%SZ>
style_md_revision: <STYLE_MD_REVISION>
voices_available: [<VOICES_AVAILABLE comma-separated>]
voices_succeeded: [<voices_succeeded from summary>]
total_findings: <N>
by_severity: {BLOCKER: N, MAJOR: N, MINOR: N}
findings_index:
  - {id: T-PS-001, severity: BLOCKER, category: premature-abstraction, source_file: PLAN.md, title: "..."}
  # ... one entry per finding
---

# Plan-Style Audit — <SLUG>

Findings ranked BLOCKER / MAJOR / MINOR. **Delete any finding you don't want to amend.** Then `/z-amend --from z-harness/<SLUG>/PLAN_STYLE_AUDIT.md`.

## BLOCKER — would cause future bugs or maintenance pain

(findings with severity=BLOCKER, each as an amendment block; omit section if empty)

- [ ] T-PS-NNN. <title>
  **Source:** <source_file>:<line_start>-<line_end>
  **Task:** <task_id or "n/a">
  **Proposed symbol:** <proposed_symbol or "n/a">
  **Category:** <category>
  **Voices:** <voices list, comma-separated>
  **Citation:** <citation or "none">
  **Finding:** <detail>
  **Recommendation:** <recommendation>

## MAJOR — clear quality regression vs the rest of the codebase

(findings with severity=MAJOR; omit section if empty)

## MINOR — design hygiene

(findings with severity=MINOR; omit section if empty)
```

Rules:
- Omit any severity section that has zero findings — do not emit an empty `## MAJOR` section.
- For `line_start`/`line_end`: if both are non-null, format as `<source_file>:<line_start>-<line_end>`. If only `line_start` is non-null, format as `<source_file>:<line_start>`. If both are null, just `<source_file>`.
- `voices` in each finding block: use the per-finding `voices` array from the merged `ALL_FINDINGS` list.
- `Citation`: use the `citation` field from the finding JSON. If null, write `none`.
- `Task` / `Proposed symbol`: when `null`, write `n/a`.

Write the content to **both** paths:
1. `$BASE/PLAN_STYLE_AUDIT.md` — canonical (overwrites any prior file)
2. `$BASE/archive/$RUN/PLAN_STYLE_AUDIT.md` — snapshot (identical content)

### Step 4f — Emit per-finding telemetry

For each finding emit one `plan_style_finding_emitted` event:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_style_finding_emitted \
  "$(printf '{"slug":"%s","run_id":"%s","id":"%s","severity":"%s","category":"%s","voices_count":%d}' \
     "$Z_HARNESS_SLUG" "$RUN" "$FINDING_ID" "$FINDING_SEVERITY" "$FINDING_CATEGORY" "$VOICES_COUNT")"
```

### Step 4g — Log plan_style_run_end

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_style_run_end \
  "$(python3 -c '
import json, sys
slug, run_id, total, by_sev_json, by_cat_json, voices_s, voices_f, dismissal_matches = \
  sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7], int(sys.argv[8])
print(json.dumps({
  "slug": slug,
  "run_id": run_id,
  "total_findings": total,
  "by_severity": json.loads(by_sev_json),
  "by_category": json.loads(by_cat_json),
  "voices_succeeded": voices_s.split(",") if voices_s else [],
  "voices_failed": voices_f.split(",") if voices_f else [],
  "dismissal_matches": dismissal_matches,
}))
' "$Z_HARNESS_SLUG" "$RUN" "$TOTAL_FINDINGS" "$BY_SEVERITY_JSON" "$BY_CATEGORY_JSON" "$VOICES_SUCCEEDED" "$VOICES_FAILED" "$DISMISSAL_MATCHES")"
```

---

## Phase 5 — Final user message and gate

Send `PushNotification` (if policy ≠ `off`): "Plan-style audit complete: N findings surfaced (B BLOCKER / M MAJOR / m MINOR)."

**Resolver pre-check — run before invoking `AskUserQuestion`:**

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
- **`halt`:** Emit `plan_style_halt` event and exit cleanly — do NOT invoke `AskUserQuestion`:
  ```bash
  if [[ "$RESULT" == "halt" ]]; then
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_style_halt \
      "$(printf '{"reason":"no_ask_blocked","question_id":"workflow.audit_to_amend","rule_id":"no_ask_halt"}')"
    echo "halt: no_ask_blocked on workflow.audit_to_amend" >&2
    exit 0
  fi
  ```

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the audit outcome
     gate (Amend now / Review and trim / Proceed as-is) via their native channel
     when resolver result is prefill or ask. Silent omission is forbidden. -->
Present the summary and ask via `AskUserQuestion` (when resolver result is `prefill` or `ask`):
- "Amend now (run `/z-amend --from z-harness/<SLUG>/PLAN_STYLE_AUDIT.md`)"
- "Review and trim — I'll edit PLAN_STYLE_AUDIT.md first, then run /z-amend myself"
- "Proceed as-is — findings acceptable, start implementation"

After writing both files, output a final message:

```
Plan-style audit complete.

Results: z-harness/<SLUG>/PLAN_STYLE_AUDIT.md
  Total findings: <N>
  BLOCKER: <N>  MAJOR: <N>  MINOR: <N>
  Voices: <VOICES_AVAILABLE>
  Run ID: <RUN>

Delete what you don't want to amend, then /z-amend --from z-harness/<SLUG>/PLAN_STYLE_AUDIT.md to apply the survivors.
```

If `DISMISSAL_MATCHES >= 3`, append:

```
Note: <N> finding(s) match prior dismissal patterns. Consider /z-style-init --amend to codify these preferences into STYLE.md so they are not raised again.
```

---

---

## Phase 9 — Elevation Proposer

After the user gate in Phase 5 resolves, run the preference elevation check:

```bash
PROPOSE_OUT="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/propose-prefs.py" --check z-audit-plan-style 2>/dev/null)"
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

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the preference
     elevation proposal question via their native channel and accept a reply.
     Silent omission is forbidden. -->
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

## Operating principles

- **Never skip the STYLE.md gate.** There is no `--no-style` flag. No STYLE.md → refuse immediately.
- **Strictly read-only.** Never modify plan artifacts or the codebase. `/z-amend` is the actuator.
- **Assume logical correctness.** Correctness, reference-reality, and race-condition findings belong to `/z-audit-plan`. Code-quality / style findings belong here. If the agent surfaces a correctness concern, pass it through verbatim under a `## Cross-dimension note` in the user message but do not promote it into the amendment list.
- **Voice degradation is a warning, not an error.** Single-voice mode is allowed; the user is informed and consensus tier-bump is disabled.
- **Archive before overwrite.** Existing `PLAN_STYLE_AUDIT.md` is always archived before being replaced — this is what powers the dismissal-extraction loop on subsequent runs.
- **Log everything** via `scripts/log-event.sh`. Event prefix is `plan_style_*`.
- **No emojis** anywhere in artifacts.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Phase 3 plan-style-reviewer Agent() call |
| `ask_user` | yes | Phase 0 multiple-candidates slug selection; Phase 5 audit outcome gate (Amend now / Review and trim / Proceed as-is); Phase 9 preference elevation proposal |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
