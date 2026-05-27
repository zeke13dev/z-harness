---
description: Audit a target component across one or more dimensions (correctness / perf / cleanliness / design). Pre-flight scopes (target, dimensions, optional rubric file), spawns one auditor subagent per dimension in parallel, runs bundled Gemini+Codex cons...
role: workflow
---

You are running **z-harness `/z-audit`** — a structured, read-only audit pipeline. The output is `REPORT.md` (everything found) plus a curated `TASKS.md` (actionable subset, in `/z-implement-all`-compatible format) under `$Z_HARNESS_PLAN_DIR-audit/`.

Target (from `$ARGUMENTS`):

$ARGUMENTS

**If the target above is empty** — use `AskUserQuestion` to ask "What should I audit?" before proceeding. Do not invent.

This command is **read-only**. Never edit the target. Fixes happen later via `/z-implement-all` consuming the emitted `TASKS.md`.

## Finding promotion contract

`/z-audit` is a producer of the shared review-family promotion contract:

- `REPORT.md` is the evidence artifact. It preserves every accepted finding, consult addition/drop, and the "one reason this might be wrong" pushback.
- `TASKS.md` is the promotion artifact. It contains only actionable findings that are safe to hand to `/z-implement-all`.

Each promoted audit task must preserve the finding's source dimension, severity, evidence, files, recommendation, and verifiable acceptance criteria. Observations with no clear fix stay in `REPORT.md`. Structural or premise-level findings that exceed the audit auto-bail thresholds become `escalation.md` instead of task blocks. This command may use its own severity labels and filenames, but the artifact must remain task-shaped and consumable by `/z-implement-all`.

## --scope-from flag handling (parsed BEFORE Setup)

Parse `$ARGUMENTS` for `--scope-from <chunk-spec>` **immediately — before slug derivation, doc-fetcher, version stamp, or run_start logging**. This ordering ensures recursive sub-flows do not pollute the parent run's slug or events.

**If `--scope-from` is present:**

1. Extract `CHUNK_SPEC` (the value immediately following `--scope-from`).
2. Set `SKIP_PHASE_0=true` immediately.
3. Resolve the chunk:
   - **Bare chunk ID** (e.g. `C1` — no `/` in the value): locate the parent run's SCOPE.json at `z-harness/<parent-slug>/archive/$Z_HARNESS_PARENT_RUN_ID/SCOPE.json`. The `$Z_HARNESS_PARENT_RUN_ID` env var is set by the HEAVY fan-out parent when spawning sub-flows. If `$Z_HARNESS_PARENT_RUN_ID` is unset, halt with `AskUserQuestion`: "Cannot resolve bare chunk ID `<id>` — no \$Z_HARNESS_PARENT_RUN_ID in environment. Pass a full path instead (e.g. `/abs/path/SCOPE.json#<id>`)."
   - **Absolute path with fragment** (e.g. `/abs/path/SCOPE.json#C1`): split on `#` to yield `(scope_json_path, chunk_id)`. Use `scope_json_path` directly.
4. Read the resolved SCOPE.json. Parse the `chunks` array. Find the chunk whose `id` matches the chunk ID.
   - If no matching chunk: emit event `scope_from_chunk_not_found` and halt with `AskUserQuestion`: "Chunk `<id>` not found in SCOPE.json. Valid chunk ids: <list>."
5. Set `SCOPE_HINT` to the matched chunk's `scope_hint` field.
6. Log event: `scope_from_resolved` with payload `{"chunk_id": "<id>", "scope_hint": "<SCOPE_HINT>", "parent_scope_json": "<path>"}`.

**Anti-sprawl invariant:** `SKIP_PHASE_0=true` alone enforces this. Sub-flows cannot recursively go HEAVY because Phase 0's HEAVY dispatch branch never executes when `SKIP_PHASE_0` is set.

**If `--scope-from` is absent:** `SKIP_PHASE_0` is unset. Phase 0 (T009) will run if present; `SCOPE_HINT` is unset.

## Setup

1. **Sanitize `$ARGUMENTS`** — strip the `--scope-from <chunk-spec>` token pair (if present) before using `$ARGUMENTS` for slug derivation, doc-fetcher dispatch, or target parsing. The sanitized value is used for all subsequent steps.
2. **Derive slug** — short kebab-case like `audit-<component>` (e.g. target `strategies/kxbtc15m_fade_extremes` → `audit-kxbtc15m`). Confirm via `AskUserQuestion` if non-obvious. Check `ls z-harness/` first for collisions.
3. Export `Z_HARNESS_SLUG=<slug>-audit`.
4. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>-audit`.
5. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
6. **Version stamp + log:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["target"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" audit_run_start "$START_PAYLOAD"
   ```
7. Notification policy: see [docs/human/config.md](docs/human/config.md) (notify.level key).
8. If `docs/llm/INDEX.json` exists → dispatch `doc-fetcher` (Haiku) to get the concept list overlapping the audit target. Do NOT read INDEX.json or per-concept JSONs from main thread.
   ```
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
         description="Doc context for audit <slug>",
         prompt="query: which concepts cover <audit target paths>?\nrepo_root: <abs path>\ndepth: summary")
   ```
   The orchestrator captures the returned concept slugs and passes the corresponding `docs/llm/<slug>.json` paths to auditors as `relevant_docs` (the auditors then read them themselves — they're fresh-context already).

`$BASE = $Z_HARNESS_PLAN_DIR/`.

## Phase 0 — Scope probe

**Check `SKIP_PHASE_0` first.** If `SKIP_PHASE_0=true` (set by `--scope-from` flag handling above), skip this entire section immediately and proceed to Phase 1. Do not dispatch scope-probe, do not write SCOPE files, do not log scope_probe_* events.

If `SKIP_PHASE_0` is not set, execute the following:

### Step 0.1 — Define axis taxonomy and dispatch scope-probe

```
AXIS_TAXONOMY=["per_dimension","per_component","per_risk_domain","per_workflow"]
```

Log event `scope_probe_start`:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_start \
  '{"axis_taxonomy":["per_dimension","per_component","per_risk_domain","per_workflow"]}'
```

Dispatch scope-probe:
```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="scope-probe",
  description="Scope probe for audit <slug>",
  prompt="host_command: z-audit\ntopic: <sanitized $ARGUMENTS>\naxis_taxonomy: [\"per_dimension\",\"per_component\",\"per_risk_domain\",\"per_workflow\"]\nrepo_root: <abs path to repo root>\nrun_id: <$RUN>"
)
```

### Step 0.2 — Parse the hybrid return

Read the scope-probe return line-by-line. Collect `KEY: VALUE` lines that appear **before** the first ` ```json ` fence marker. Any line-prefix headers found inside the fence are malformed (parser error).

Extract line-prefix fields:
- `STATUS` — one of `classified`, `refused`, `bad_input`
- `MODE` — one of `LIGHT`, `MEDIUM`, `HEAVY`
- `AXIS` — axis name from `AXIS_TAXONOMY` or `none`
- `CONFIDENCE` — `high`, `medium`, or `low`
- `REASON_CODES` — comma-separated codes
- `REASON` — one-line description

Extract the fenced JSON block using: ` ```json\n(.*?)``` ` (same pattern as review-agent). Parse `chunks`, `seams_counted`, `candidates_walked` from the JSON.

**On any parse failure** (missing line-prefix headers, no fenced block, malformed JSON, or prefix-inside-fence):
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_malformed \
  '{"reason":"<parse failure description>","raw_truncated":"<first 200 chars of raw response>"}'
```
Treat as `STATUS: refused`, `MODE: MEDIUM`, `chunks: []`. Proceed to Step 0.3 (refused branch). Never retry on parse failure.

**On `STATUS: bad_input`:**
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_malformed \
  '{"reason":"bad_input from scope-probe","raw_truncated":"<first 200 chars of raw response>"}'
```
Treat as `STATUS: refused`, `MODE: MEDIUM`, `chunks: []`. Proceed to Step 0.3 (refused branch).

**On `STATUS: refused`:**
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_classified \
  '{"status":"refused","mode":"MEDIUM","axis":"none","confidence":"<CONFIDENCE>","reason_codes":"<REASON_CODES>","reason":"<REASON>"}'
```
`MODE=MEDIUM`, `chunks=[]`. Proceed to Step 0.3 (refused/MEDIUM branch).

**On `STATUS: classified`:**
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_classified \
  '{"status":"classified","mode":"<MODE>","axis":"<AXIS>","confidence":"<CONFIDENCE>","reason_codes":"<REASON_CODES>","reason":"<REASON>","seams_counted":<seams_counted>,"candidates_walked":<candidates_walked>}'
```

### Step 0.3 — Write SCOPE.json (archive-first, then live)

Assemble the SCOPE.json payload:
```python
SCOPE_JSON = {
  "host_command":        "z-audit",
  "slug":                "<slug>",
  "last_run_id":         "<$RUN>",
  "last_updated":        "<ISO 8601 UTC timestamp now>",
  "mode":                "<MODE>",
  "axis":                "<AXIS>",
  "confidence":          "<CONFIDENCE>",
  "reason_codes":        [<parsed from REASON_CODES comma-separated>],
  "chunks":              <chunks array from JSON, or []>,
  "seams_counted":       <seams_counted or 0>,
  "candidates_walked":   <candidates_walked or 0>,
  "scope_probe_version": "1"
}
# For LIGHT mode only: include dimensions_hint (derived from topic; see Step 0.4)
```

**Write archive copy first (atomic tmp+rename):**
```bash
ARCHIVE_SCOPE="$Z_HARNESS_PLAN_DIR/archive/$RUN/SCOPE.json"
ARCHIVE_TMP="${ARCHIVE_SCOPE}.tmp"
python3 -c "import json,sys; print(json.dumps(json.loads(sys.argv[1]),indent=2))" "$SCOPE_JSON_STR" > "$ARCHIVE_TMP" \
  && mv "$ARCHIVE_TMP" "$ARCHIVE_SCOPE"
```

If the archive write fails (any step errors), abort Phase 0 entirely. Do not write the live file. Log event:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_classified \
  '{"status":"archive_write_failed","mode":"MEDIUM","note":"proceeding as MEDIUM"}'
```
Host proceeds as MEDIUM. Skip to Phase 1.

**Write live file (overwrite):**
```bash
LIVE_SCOPE="$Z_HARNESS_PLAN_DIR/SCOPE-audit.json"
python3 -c "import json,sys; print(json.dumps(json.loads(sys.argv[1]),indent=2))" "$SCOPE_JSON_STR" > "$LIVE_SCOPE"
```

### Step 0.4 — Branch on MODE

**LIGHT branch** (`MODE: LIGHT`):

Derive `dimensions_hint` from the topic. Inspect the topic (sanitized `$ARGUMENTS`) and the seam evidence: identify which of `correctness`, `perf`, `cleanliness`, `design` are most relevant to the narrow component described. Typically: a single-file target with no seams narrows to 1–2 dimensions. Add `dimensions_hint` to the SCOPE.json payload and re-write both archive and live files with this field included.

SCOPE.json now has `"dimensions_hint": ["<dim1>", ...]`. Phase 1 will consume this.

**MEDIUM branch** (`MODE: MEDIUM`, including refused/fallback):

SCOPE.json populated without `dimensions_hint`. Phase 1 proceeds with interactive dimension selection. No further action in Phase 0.

**HEAVY branch** (`MODE: HEAVY`):

Log event `scope_fanout_dispatched`:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_fanout_dispatched \
  "$(python3 -c "import json,sys; chunks=json.loads(sys.argv[1]); print(json.dumps({'chunk_count':len(chunks),'chunks':[c['id'] for c in chunks],'axis':sys.argv[2]}))" "$CHUNKS_JSON" "$AXIS")"
```

Dispatch N parallel `/z-audit` sub-flows (one per chunk in `chunks`), all in a single message:

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="orchestrator",
  description="z-audit sub-flow chunk <chunk-id>",
  prompt="Run /z-audit <sanitized $ARGUMENTS> --scope-from <abs path to ARCHIVE_SCOPE>#<chunk-id>\n\nZ_HARNESS_PARENT_RUN_ID: <$RUN>\n\nThis is a HEAVY fan-out sub-flow spawned by the parent z-audit run <$RUN>. The parent run ID is <$RUN> — include it in the sub-flow environment as $Z_HARNESS_PARENT_RUN_ID so bare chunk ID resolution works correctly."
)
```

Wait for all N sub-flows to return. Collect their returns.

After all sub-flows complete, dispatch `scope-reconciler-audit`:
```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="scope-reconciler-audit",
  description="Reconcile HEAVY fanout for audit <slug>",
  prompt="host_run_id: <$RUN>\nchunks: <JSON array of {id, findings_path} for each completed sub-flow — findings_path is the per-chunk findings file produced by that sub-flow>\ntarget_slug: <slug>\naxis: <AXIS>\noutput_dir: <abs path to $Z_HARNESS_PLAN_DIR>"
)
```

Parse reconciler return. The reconciler's `REPORT_CONTENT:` field contains the full REPORT.md text. Write it:
```bash
python3 -c "import sys; open(sys.argv[1],'w').write(sys.argv[2])" \
  "$Z_HARNESS_PLAN_DIR/REPORT.md" "<REPORT_CONTENT from reconciler>"
```

Write each chunk artifact per reconciler's `CHUNK_ARTIFACTS:` list:
- For entries with `source`: copy the source file to `dest`.
- For entries with `content`: write the content string to `dest`.

Log event `scope_fanout_reconciled`:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_fanout_reconciled \
  "$(python3 -c "import json,sys; r=json.loads(sys.argv[1]); print(json.dumps({'unified_verdict':r['UNIFIED_VERDICT'],'chunks_total':r['COUNTS']['chunks_total'],'chunks_failed':r['COUNTS']['chunks_failed'],'findings_after_dedup':r['COUNTS']['findings_after_dedup']}))" "$RECONCILER_RETURN_JSON")"
```

**After HEAVY reconciliation: skip Phase 2 (standard auditor dispatch) — the per-chunk sub-flows have already performed auditing. Proceed directly to Phase 3 (merge findings into REPORT.md is already done by reconciler), then Phase 4 (Bundled cross-LLM consult), Phase 5 (Promote to TASKS.md), etc.**

**HEAVY reconciler failure fallback:** If `scope-reconciler-audit` returns `STATUS: unable_to_complete`:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_fanout_reconciled \
  '{"status":"reconciler_failed","fallback":"concatenated_chunks"}'
```
Write a `REPORT.md` with `## Reconciliation failed — raw chunks below` as the header, then concatenate each chunk's findings file verbatim under `## Chunk: <chunk-id>` headings. Continue to Phase 5.

## Auto-bail thresholds (check after Phase 4)

If the merged findings count exceeds:

- **>30 findings total**, OR
- **>10 CRITICAL/HIGH findings** (indicates structural problems, not point fixes)

→ STOP. Write `$BASE/escalation.md` summarizing the scope. Push-notify: "Audit surfaced N findings; recommend `/z-plan` for a full restructure rather than a TASKS.md queue." Do not generate TASKS.md.

## Phase 1 — Pre-flight scoping

If `SCOPE_HINT` is set (from `--scope-from`), use `SCOPE_HINT` as the resolved target — do not re-derive the target from `$ARGUMENTS`. Skip the target confirmation step.

If `$ARGUMENTS` supplied a target + the user already named dimensions in prose, skip ahead. Otherwise use `AskUserQuestion` to collect:

1. **Dimensions** — multi-select (≥1 required):

   **Before asking the user**, check `$Z_HARNESS_PLAN_DIR/SCOPE-audit.json` (the live SCOPE file written by Phase 0). If it exists for this run (`last_run_id` matches `$RUN`) AND `mode` is `LIGHT` AND `dimensions_hint` is a non-empty array:
   - Auto-confirm the `dimensions_hint` list. Do NOT ask the user which dimensions to audit. Proceed as if the user selected those dimensions.
   - Inform the user: "Phase 0 scope probe suggested dimensions: <dimensions_hint list>. Proceeding with those."

   If `SCOPE-audit.json` does not exist, `last_run_id` does not match, `mode` is not `LIGHT`, or `dimensions_hint` is absent/empty — ask the user interactively:
   - `correctness` — bugs, off-by-ones, math, look-ahead, polarity, invariants
   - `perf` — slowdowns, allocations, blocking IO, redundant work
   - `cleanliness` — duplication, dead code, layering, config sprawl
   - `design` — assumptions still sound? algorithm choice still right? module boundaries earning their weight?

   **No double-scoping:** Phase 1 must not re-derive dimensions from scratch when SCOPE-audit.json provides `dimensions_hint`. Phase 0 narrows; Phase 1 confirms and proceeds.

2. **Rubric file (optional)** — if the repo has rubric files under `.claude/audit-rubrics/`, present each as an option. The rubric is a domain-specific checklist that supplements (or replaces) the generic dimension checklist. Discovery:
   ```bash
   ls .claude/audit-rubrics/*.md 2>/dev/null
   ```
   Offer one per matching rubric, plus a "none — use generic checklist" option.

3. **Target confirmation** — show what you read from `$ARGUMENTS`; let user correct.

Checkpoint: `$BASE/archive/$RUN/phase1-scope.md` with the resolved (target, dimensions, rubric_path).

## Phase 2 — Parallel auditor dispatch

Spawn one `auditor` subagent **per selected dimension**, in parallel, in a single message:

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="auditor",
  description="<dim> audit of <slug>",
  prompt="DIMENSION: <dim>\nTARGET: <abs path> — <one-line description>\nRUBRIC_PATH: <abs path or empty>\n$BASE: <abs path to $BASE>\nrelevant_docs:\n  - <doc1>\n  - <doc2>\n\nFollow your agent definition. Emit findings to $BASE/findings-<dim>.md and return STATUS + COUNTS + VERDICT."
)
```

Each auditor writes `$BASE/findings-<dim>.md` and returns a structured summary. Collect all returns.

**If any auditor returns `unable_to_complete`** — surface the reason via `AskUserQuestion`: retry that dimension / skip it / abort the audit.

Checkpoint: `$BASE/archive/$RUN/phase2-auditor-returns.md` (concatenate the four return blocks).

## Phase 3 — Merge findings

Build `$BASE/REPORT.md` (full set, organized by dimension):

```markdown
# Audit — <slug>

- **Date (UTC):** YYYY-MM-DDTHH:MMZ
- **Target:** <abs path + one-line description>
- **Dimensions audited:** <comma-separated>
- **Rubric:** <path or "generic">

## Summary
- <2-5 bullets across all dimensions>

## Findings — correctness
<verbatim from findings-correctness.md>

## Findings — perf
<verbatim from findings-perf.md>

... (one section per dimension)

## Cross-dimension findings
<findings flagged by multiple auditors via CROSS_DIMENSION: lines — consolidate here>

## Verdicts
- correctness: PASS | NEEDS-WORK | BLOCKED
- perf:        ...
- cleanliness: ...
- design:      KEEP | REFACTOR | SCRAP
```

## Phase 4 — Bundled cross-LLM consult on findings

Spawn both consultants in parallel against `REPORT.md`:

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-primary",
  description="Audit findings review (Gemini) for <slug>",
  prompt="MODE: audit-review\n\nA target has been audited across <dimensions>. Here is the full REPORT:\n\n<paste REPORT.md>\n\nTwo asks:\n1. What significant findings are MISSING — issues the dimension auditors should have caught but didn't?\n2. Which listed findings are TRIVIAL or speculative and should be dropped before promotion to TASKS.md?\n\nBe specific. Cite path:line. Severity-rank any additions."
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-secondary",
  description="Audit findings review (Codex) for <slug>",
  prompt="MODE: audit-review\n\n<same prompt body>"
)
```

Both transcripts archive themselves under `$BASE/archive/$RUN/transcripts/`.

**When both return:**

1. For each addition: apply the "one reason this might be wrong" check before accepting.
2. For each suggested drop: confirm by re-reading the cited code.
3. Update `REPORT.md` with `## Consult additions` and `## Consult drops` sections noting what changed and which consultant flagged it.

**Check auto-bail thresholds now** (see top). If the post-consult count exceeds the bail thresholds, escalate to `/z-plan`.

## Phase 5 — Promote to TASKS.md

Only actionable findings go into TASKS.md. An observation that has no clear fix stays in REPORT.md.

Write `$BASE/TASKS.md` in the **exact format `/z-implement-all` consumes** (mirror `agents/implementer.md` shape):

```markdown
# Audit TASKS — <slug>

Status legend: `[ ]` pending · `[~]` in_progress · `[x]` done.

### [ ] T001 — [SEVERITY] short subject
- One-paragraph context: why this matters, what evidence supports it (cite the REPORT.md finding ID).
- **Files:** `<path>:<line>` (modified).
- **Depends on:** none | T00X.
- **Acceptance:** verifiable criteria (test name, benchmark delta, code removed, abstraction extracted, etc.).
- **REMOTE_VERIFY:** <cargo / verify command> (if applicable — see /z-plan Phase 8 rules)
- **DOCS:** <concept-slug> (if the fix touches a documented surface)

### [ ] T002 — [SEVERITY] ...
```

Severity prefix in subject: `[CRITICAL] | [HIGH] | [MED] | [LOW]`. Group by phase (Phase A / B / …) when tasks have ordering dependencies.

**Note in `$BASE/SPEC.md`:** `/z-implement-all` will read `$BASE/SPEC.md`. Audits don't produce a SPEC, but the implementer reads it. Write a minimal `$BASE/SPEC.md`:

```markdown
# Audit SPEC — <slug>

This SPEC was produced by `/z-audit`, not `/z-plan`. Each task in TASKS.md references a finding in REPORT.md; the finding's "Recommendation" line is the per-task spec. The implementer should:

1. Read the task's Files + Acceptance.
2. Read the cited REPORT.md finding for full context.
3. Apply the Recommendation surgically — no scope expansion beyond Files.
```

Also write a minimal `$BASE/PLAN.md` pointing to REPORT.md:

```markdown
# Audit PLAN — <slug>

See `REPORT.md` for full findings and `TASKS.md` for the actionable queue.

Goals: address all CRITICAL + HIGH severity findings.
Non-goals: structural refactors (those need `/z-plan`).
```

This three-file set (SPEC.md / PLAN.md / TASKS.md) is what `/z-implement-all` requires.

## Phase 6 — Codex safety gate on TASKS.md

Spawn the reviewer against the audit-produced TASKS.md (the diff in this case is the TASKS.md itself):

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="reviewer",
  description="Codex review of audit TASKS for <slug>",
  prompt="task id: <slug>-audit-tasks\ntask description: review the audit-produced TASKS.md for soundness — would executing these tasks make the target better or risk regression?\nacceptance criteria: every task addresses a real finding in REPORT.md with a verifiable acceptance line\ndiff.patch path: (n/a — review the file directly)\nchanged files: <abs path to $BASE/TASKS.md>\nrelevant_docs: <any docs/llm paths from Setup step 7>\n$BASE: <abs path to $BASE>\n\nFlag: tasks that would regress invariants, tasks with vague acceptance, severity inflation, scope creep beyond the cited finding."
)
```

Parse the return (capped at 8 KB):
- **Blockers** → re-edit the affected TASKS.md entries; re-run review once. Second failure → halt with `AskUserQuestion`.
- **Majors** → fix in place, then accept.
- **No blockers/majors** → accept.

## Phase 7 — Present + finalize

Send `PushNotification` (if policy != `off`): "Audit complete — <N> tasks queued."

Brief summary to user (3-5 bullets):
- Target audited and dimensions covered
- Top 3 findings by severity
- Task count and recommended next step (`/z-implement-all` if findings are point fixes; `/z-plan` if structural)
- Pointers: `$BASE/REPORT.md`, `$BASE/TASKS.md`

Log run end:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" audit_run_end \
  "$(printf '{"status":"complete","findings":%d,"tasks":%d,"dimensions":"%s"}' "$N_FINDINGS" "$N_TASKS" "$DIMS")"
```

## Hard rules

- **Read-only.** Never edit the target. Ever.
- **Never skip the codex safety gate** on the produced TASKS.md.
- **Always emit cross-LLM consult** in Phase 4 — both Gemini and Codex, in parallel.
- **One auditor per dimension, in parallel.** Never serialize.
- **TASKS.md format must match what `/z-implement-all` consumes** — otherwise the audit is a dead-end artifact.
- **No emojis** anywhere in artifacts.
