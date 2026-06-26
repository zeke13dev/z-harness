---
name: z-audit
disable-model-invocation: false
description: Audit a target component across one or more dimensions (correctness / perf / cleanliness / design). Pre-flight scopes (target, dimensions, optional rubric file), spawns one auditor subagent per dimension in parallel, runs bundled Gemini+Codex consult on findings, emits REPORT.md + TASKS.md under $Z_HARNESS_PLAN_DIR-audit/ in the exact shape /z-execute consumes. Read-only — never edits the target.
argument-hint: <target path or component name> [--scope-from <chunk-spec>]
runtime: c1
driver_features_required:
  - subagent
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-audit`** — a structured, read-only audit pipeline. The output is `REPORT.md` (everything found) plus a curated `TASKS.md` (actionable subset, in `/z-execute`-compatible format) under `$Z_HARNESS_PLAN_DIR-audit/`.

Target (from `$ARGUMENTS`):

$ARGUMENTS

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the question
     "What should I audit?" via their native channel and accept a text reply.
     Silent omission is forbidden. -->
**If the target above is empty** — use `AskUserQuestion` to ask "What should I audit?" before proceeding. Do not invent.

This command is **read-only**. Never edit the target. Fixes happen later via `/z-execute` consuming the emitted `TASKS.md`.

## Finding promotion contract

`/z-audit` is a producer of the shared review-family promotion contract:

- `REPORT.md` is the evidence artifact. It preserves every accepted finding, consult addition/drop, and the "one reason this might be wrong" pushback.
- `TASKS.md` is the promotion artifact. It contains only actionable findings that are safe to hand to `/z-execute`.

Each promoted audit task must preserve the finding's source dimension, severity, evidence, files, recommendation, and verifiable acceptance criteria. Observations with no clear fix stay in `REPORT.md`. Structural or premise-level findings that exceed the audit auto-bail thresholds become `escalation.md` instead of task blocks. This command may use its own severity labels and filenames, but the artifact must remain task-shaped and consumable by `/z-execute`.

## --scope-from flag handling (parsed BEFORE Setup)

Parse `$ARGUMENTS` for `--scope-from <chunk-spec>` **immediately — before slug derivation, doc-fetcher, version stamp, or run_start logging**. This ordering ensures recursive sub-flows do not pollute the parent run's slug or events.

**If `--scope-from` is present:**

1. Extract `CHUNK_SPEC` (the value immediately following `--scope-from`).
2. Set `SKIP_PHASE_0=true` immediately.
3. Resolve the chunk:
   - **Absolute path with fragment** (e.g. `/abs/path/SCOPE.json#C1`): split on `#` to yield `(scope_json_path, chunk_id)`. Use `scope_json_path` directly. **HEAVY fan-out always uses this form** — it interpolates the absolute ARCHIVE_SCOPE path directly into the sub-flow prompt, so bare chunk ID resolution is never needed for HEAVY-spawned sub-flows.
   - **Bare chunk ID** (e.g. `C1` — no `/` in the value): This form is for manual invocation only. The caller prompt must include both a `PARENT_RUN_ID:` line AND a `PARENT_SLUG:` line. Extract both from the prompt. Locate the parent run's SCOPE.json at `z-harness/<PARENT_SLUG>/archive/<PARENT_RUN_ID>/SCOPE.json`. If either `PARENT_RUN_ID` or `PARENT_SLUG` is absent from the prompt context, store `SCOPE_FROM_ERROR="bare_chunk_no_context"` and halt after Setup: "Cannot resolve bare chunk ID `<id>` — no PARENT_RUN_ID or PARENT_SLUG in context. Pass a full path instead (e.g. `/abs/path/SCOPE.json#<id>`)."
4. Read the resolved SCOPE.json. Parse the `chunks` array. Find the chunk whose `id` matches the chunk ID.
   - If no matching chunk: store the error in `SCOPE_FROM_ERROR="chunk_not_found"` and store valid IDs in `SCOPE_FROM_VALID_IDS`. The actual halt via `AskUserQuestion` happens after Setup (Step 0 of Setup, after `$RUN` is established). Do not log any event yet.
5. Set `SCOPE_HINT` to the matched chunk's `scope_hint` field.
6. **Defer all `log-event.sh` calls to after Setup.** At this pre-Setup stage, `$RUN` does not yet exist, so no events may be logged. Store `SCOPE_FROM_RESOLVED_PAYLOAD='{"chunk_id": "<id>", "scope_hint": "<SCOPE_HINT>", "parent_scope_json": "<path>"}'` for logging after Setup initializes `$RUN`.

7. **Artifact Scout inheritance:** child audit flows invoked with `--scope-from` inherit the parent's artifact-scout context. Set `ARTIFACT_SCOUT_PARENT_CONTEXT="$scope_json_path"` (or the parent archive dir when known) and `ARTIFACT_SCOUT_SKIP_HISTORICAL_RESCAN=true`. A `--scope-from` child MUST NOT run `scripts/artifact-scout-inventory.py` and MUST NOT dispatch `artifact-scout`; it may surface the parent `artifact-scout.md` warning summary if the parent archive is available.


**After Setup completes (RUN and archive dirs exist):** If `SCOPE_FROM_ERROR` is set, halt with `AskUserQuestion`: "Chunk `<id>` not found in SCOPE.json. Valid chunk ids: <SCOPE_FROM_VALID_IDS>." Execute **Run Brief — halt finalize** with reason `chunk <id> not found`.
Otherwise log:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_from_resolved "$SCOPE_FROM_RESOLVED_PAYLOAD"
```

**Anti-sprawl invariant:** `SKIP_PHASE_0=true` alone enforces this. Sub-flows cannot recursively go HEAVY because Phase 0's HEAVY dispatch branch never executes when `SKIP_PHASE_0` is set.

**If `--scope-from` is absent:** `SKIP_PHASE_0` is unset. Phase 0 (T009) will run if present; `SCOPE_HINT` is unset.

## Setup

1. **Sanitize `$ARGUMENTS`** — strip the `--scope-from <chunk-spec>` token pair (if present) before using `$ARGUMENTS` for slug derivation, doc-fetcher dispatch, or target parsing. The sanitized value is used for all subsequent steps.
<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the slug
     confirmation question via their native channel if non-obvious. Silent
     omission is forbidden. -->
2. **Derive slug** — short kebab-case like `audit-<component>` (e.g. target `strategies/kxbtc15m_fade_extremes` → `audit-kxbtc15m`). Confirm via `AskUserQuestion` if non-obvious. Check `bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" all_plan_slugs` first for collisions.
3. Export `Z_HARNESS_SLUG=<slug>-audit`.
4. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>-audit`.
5. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
6. **Version stamp + log:**
   ```bash
   export Z_HARNESS_SESSION_ID="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" session-id)"
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["target"] = sys.argv[2]; v["session_id"] = sys.argv[3]; v["command"] = "z-audit"
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>" "$Z_HARNESS_SESSION_ID")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" audit_run_start "$START_PAYLOAD"
   ```

   **Run Brief init (immediately after `audit_run_start`).** Registry: `/z-audit`, profile `full`, artifact `REPORT.md`.
   ```bash
   CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"
   RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
   AUDIT_INTENT="$(python3 -c 'import json,sys; t=json.loads(sys.argv[1]).get("target","").strip(); print(("Audit: "+t)[:240] if t else "Audit target component")' "$START_PAYLOAD")"
   bash "$RB_SH" init --run "$RUN" --command /z-audit --slug "$Z_HARNESS_SLUG" --profile full --intent "$AUDIT_INTENT"
   export RUN_BRIEF_PROFILE=full
   export RUN_BRIEF_ARTIFACT="$Z_HARNESS_PLAN_DIR/REPORT.md"
   export RUN_BRIEF_ARTIFACT_FALLBACKS=""
   ```

   **Active-plan registration (immediately after audit_run_start).** Register this run in the shared registry. Graduated failure policy — never silent-continue on failure:
   ```bash
   python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" register \
     --run-id "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-audit --phase audit \
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

   **FINALIZE_STATUS rule:** On any run-ending halt after `REG_RC == 0`, run **Run Brief — halt finalize** (below), set `FINALIZE_STATUS=aborted`, then `deregister --status aborted`. On normal completion (Phase 7), deregister with `complete`. If register failed, do NOT deregister.

   **Kernel path resolution (once per run, immediately after audit_run_start):**
   ```bash
   KERNEL_PATH="$(bash scripts/resolve-kernel.sh 2>/dev/null || true)"
   ```
   Resolve the kernel path exactly once here. When `KERNEL_PATH` is non-empty, inject `kernel_path: <KERNEL_PATH>` as a line in the `Agent(prompt=...)` of every behavioral-agent dispatch in this run (auditor, consultant-primary, consultant-secondary, reviewer). Omit the line entirely when `KERNEL_PATH` is empty — the agent's static fallback handles self-resolution in that case. Do NOT inject kernel content — inject the path string only.

7. Notification policy: see [docs/human/config.md](docs/human/config.md) (notify.level key).
8. **Artifact Scout preflight (skipped for `--scope-from` children):**
   If `ARTIFACT_SCOUT_SKIP_HISTORICAL_RESCAN=true`, surface the inherited parent scout context and continue; do not rescan historical artifacts.

   Otherwise run deterministic inventory and classifier before doc-fetcher, scope-probe, auditor, consultant, or reviewer dispatch:
   ```bash
   REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
   ARTIFACT_SCOUT_INVENTORY="$Z_HARNESS_PLAN_DIR/archive/$RUN/artifact-scout-inventory.json"
   python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/artifact-scout-inventory.py" \
     --command /z-audit --slug "$Z_HARNESS_SLUG" --run-id "$RUN" \
     --repo-root "$REPO_ROOT" --plan-dir "$Z_HARNESS_PLAN_DIR" \
     --task "$SANITIZED_ARGUMENTS" --output "$ARTIFACT_SCOUT_INVENTORY"
   ARTIFACT_SCOUT_EVENT_PAYLOAD="$(python3 - "$ARTIFACT_SCOUT_INVENTORY" <<'PYEOF'
import json, sys
path = sys.argv[1]
data = json.load(open(path, encoding="utf-8"))
print(json.dumps({
  "command": data.get("command"),
  "slug": data.get("slug"),
  "run_id": data.get("run_id"),
  "artifact_path": path,
  "source_status": data.get("source_status", {}),
  "mandatory_candidate_count": len(data.get("mandatory_candidates") or []),
  "historical_candidate_count": len(data.get("historical_candidates") or []),
  "active_record_count": len(data.get("active_records") or []),
  "worktree_count": len(data.get("worktrees") or []),
  "truncated": bool(data.get("truncated")),
}, separators=(",", ":")))
PYEOF
)"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" artifact_scout_inventory_complete "$ARTIFACT_SCOUT_EVENT_PAYLOAD"
   ```
   The `artifact_scout_inventory_complete` payload MUST include `command`, `slug`, `run_id`, `artifact_path`, `source_status`, `mandatory_candidate_count`, `historical_candidate_count`, `active_record_count`, `worktree_count`, and `truncated` from the inventory JSON.
   ```
   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this artifact-scout
        requirement and skip the Agent() call. Skipping means continue without scout routing. -->
   Agent(
     subagent_type="artifact-scout",
     description="Artifact scout for z-audit <slug>",
     prompt="current_command: /z-audit
task_or_topic: <sanitized audit target>
route_chain_json: <current route chain JSON>
repo_root: <abs repo root>
inventory_json_path: $Z_HARNESS_PLAN_DIR/archive/$RUN/artifact-scout-inventory.json

Inline inventory JSON:
<contents printed by scripts/artifact-scout-inventory.py>"
   )
   ```
   Write the raw response to `$Z_HARNESS_PLAN_DIR/archive/$RUN/artifact-scout.md`. Emit `artifact_scout_classified`, `artifact_scout_warning`, and `artifact_scout_route` per the contract. Warning-only debug/audit similarity never routes: it never writes `route-decision.md`, never emits `artifact_scout_route`, and never advances `route_chain`. Only `ask_user` or route outcomes with `route_chain_effect: "write_route_decision"` may write a route artifact and emit `plan_route_decision`.

9. If `docs/llm/INDEX.json` exists → dispatch `doc-fetcher` (Haiku) to get the concept list overlapping the audit target. Do NOT read INDEX.json or per-concept JSONs from main thread.
   ```
   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
        requirement and skip if unavailable. Audit proceeds without doc grounding. -->
   Agent(subagent_type="doc-fetcher",
         description="Doc context for audit <slug>",
         prompt="query: which concepts cover <audit target paths>?\nrepo_root: <abs path>\ndepth: summary")
   ```
   The orchestrator captures the returned concept slugs and passes the corresponding `docs/llm/<slug>.json` paths to auditors as `relevant_docs` (the auditors then read them themselves — they're fresh-context already).

`$BASE = $Z_HARNESS_PLAN_DIR/`.

## Phase 0 — Scope probe

**Check `SKIP_PHASE_0` first.** If `SKIP_PHASE_0=true` (set by `--scope-from` flag handling above), skip this entire section immediately and proceed to Phase 1. Do not dispatch scope-probe, do not write SCOPE files, do not log scope_probe_* events.

If `SKIP_PHASE_0` is not set, execute the following:

### Step 0a — Fast-path check (single-file target)

Before dispatching scope-probe, evaluate whether the target qualifies for an automatic LIGHT classification:

```bash
ARG="<sanitized $ARGUMENTS>"
ARG_LEN=${#ARG}
case "$ARG" in
  *"*"*|*"?"*|*"["*|*"{"*|*"}"*) IS_GLOB=1;;
  *) IS_GLOB=0;;
esac
EXPANDED_ARG="${ARG/#\~/$HOME}"
SCOPE_FAST_PATH=0
if [ "$IS_GLOB" -eq 0 ] && [ "$ARG_LEN" -lt 200 ] && [ -f "$EXPANDED_ARG" ]; then
  # Fast-path: single existing file, short argument, no globs → auto-classify LIGHT
  SCOPE_FAST_PATH=1
  PAYLOAD="$(python3 -c 'import json,sys; print(json.dumps({"command":sys.argv[1],"target":sys.argv[2],"arg_len":int(sys.argv[3])}))' "z-audit" "$EXPANDED_ARG" "$ARG_LEN")"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_skipped_fast_path "$PAYLOAD"
  MODE=LIGHT
  AXIS=none
  CONFIDENCE=high
  REASON_CODES=fast_path_single_file
  REASON="single-file target auto-classified as LIGHT"
  chunks=[]
  seams_counted=0
  candidates_walked=0
  # Skip to Step 0.3 with LIGHT classification; do not dispatch scope-probe Agent.
  # Proceed directly to Step 0.3 — Write SCOPE.json using MODE=LIGHT.
  # dimensions_hint is derived in Step 0.3 (LIGHT branch) per normal flow.
else
  # Multi-file / glob / large-arg path: run full scope-probe (Steps 0.1 and 0.2 below).
fi
```

If the fast-path branch was taken (`SCOPE_FAST_PATH=1`), skip Steps 0.1 and 0.2 entirely and jump to Step 0.3.

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
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement and skip if unavailable. Phase 0 scope probe cannot run
     without subagent support; default to MEDIUM mode. -->
Agent(
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
Assign safe defaults before writing SCOPE.json:
```
STATUS=refused, MODE=MEDIUM, AXIS=none, CONFIDENCE=low
REASON_CODES=["parser_error"], REASON="parse failure — defaulting to MEDIUM"
chunks=[], seams_counted=0, candidates_walked=0
```
Proceed to Step 0.3. Never retry on parse failure.

**On `STATUS: bad_input`:**
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_malformed \
  '{"reason":"bad_input from scope-probe","raw_truncated":"<first 200 chars of raw response>"}'
```
Assign safe defaults before writing SCOPE.json:
```
STATUS=refused, MODE=MEDIUM, AXIS=none, CONFIDENCE=low
REASON_CODES=["parser_error"], REASON="bad_input from scope-probe — defaulting to MEDIUM"
chunks=[], seams_counted=0, candidates_walked=0
```
Proceed to Step 0.3.

**On `STATUS: refused`:**
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_classified \
  '{"status":"refused","mode":"MEDIUM","axis":"none","confidence":"<CONFIDENCE>","reason_codes":"<REASON_CODES>","reason":"<REASON>"}'
```
`MODE=MEDIUM`, `chunks=[]`. If `AXIS` or `CONFIDENCE` or `REASON_CODES` or `REASON` were not present in the response, substitute safe defaults: `AXIS=none`, `CONFIDENCE=low`, `REASON_CODES=["parser_error"]`, `REASON="refused"`, `seams_counted=0`, `candidates_walked=0`. Proceed to Step 0.3.

**On `STATUS: classified`:**
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_classified \
  '{"status":"classified","mode":"<MODE>","axis":"<AXIS>","confidence":"<CONFIDENCE>","reason_codes":"<REASON_CODES>","reason":"<REASON>","seams_counted":<seams_counted>,"candidates_walked":<candidates_walked>}'
```

### Step 0.3 — Write SCOPE.json (archive-first, then live)

**If `MODE` is `LIGHT`: derive `dimensions_hint` first (before any write).** Inspect the topic (sanitized `$ARGUMENTS`) and seam evidence: identify which of `correctness`, `perf`, `cleanliness`, `design` are most relevant. Typically a single-file, no-seam target narrows to 1–2 dimensions. Store the result in `DIMENSIONS_HINT_LIST` (a JSON array string, e.g. `["correctness","perf"]`).

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
  # For LIGHT mode only: "dimensions_hint": <DIMENSIONS_HINT_LIST>
  # Include dimensions_hint in this payload NOW — derive it above before this step, not after.
}
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

**Write live file (atomic tmp+rename — matches archive write order; prevents partial-overwrite on parallel runs):**
```bash
LIVE_SCOPE="$Z_HARNESS_PLAN_DIR/SCOPE-audit.json"
LIVE_TMP="${LIVE_SCOPE}.tmp.$$"
python3 -c "import json,sys; print(json.dumps(json.loads(sys.argv[1]),indent=2))" "$SCOPE_JSON_STR" > "$LIVE_TMP" \
  && mv "$LIVE_TMP" "$LIVE_SCOPE"
```

### Step 0.4 — Branch on MODE

**LIGHT branch** (`MODE: LIGHT`):

`dimensions_hint` was derived and included in the SCOPE.json write in Step 0.3. No further action needed in this branch. SCOPE.json already has `"dimensions_hint": ["<dim1>", ...]`. Phase 1 will consume this.

**MEDIUM branch** (`MODE: MEDIUM`, including refused/fallback):

SCOPE.json populated without `dimensions_hint`. Phase 1 proceeds with interactive dimension selection. No further action in Phase 0.

**HEAVY branch** (`MODE: HEAVY`):

Log event `scope_fanout_dispatched`:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_fanout_dispatched \
  "$(python3 -c "import json,sys; chunks=json.loads(sys.argv[1]); print(json.dumps({'chunk_count':len(chunks),'chunks':[c['id'] for c in chunks],'axis':sys.argv[2]}))" "$CHUNKS_JSON" "$AXIS")"
```

**Soft cost estimate (non-blocking).** Call the gate helper with the HEAVY chunk count (N), display the estimate, and log the decision. This fires only here (HEAVY path); LIGHT/MEDIUM runs skip it entirely.
```bash
# workflow.pre_run_cost_gate
N_CHUNKS="$(python3 -c 'import json,sys; print(len(json.loads(sys.argv[1])))' "$CHUNKS_JSON" 2>/dev/null || echo "0")"
COST_GATE_JSON="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/pre-run-cost-gate.sh" \
  z-audit soft "$RUN" --dispatch per_dimension=$N_CHUNKS 2>/dev/null)" || COST_GATE_JSON=""
if [ -n "$COST_GATE_JSON" ]; then
  COST_HUMAN_BLOCK="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("human_block",""))' "$COST_GATE_JSON" 2>/dev/null || true)"
  [ -n "$COST_HUMAN_BLOCK" ] && printf '%s\n' "$COST_HUMAN_BLOCK"
  COST_ESTIMATED_TOKENS="$(python3 -c 'import json,sys; e=json.loads(sys.argv[1]).get("estimate",{}); print(json.dumps(e.get("estimated_tokens")))' "$COST_GATE_JSON" 2>/dev/null || echo "null")"
  COST_CONFIDENCE="$(python3 -c 'import json,sys; e=json.loads(sys.argv[1]).get("estimate",{}); print(e.get("confidence","unknown"))' "$COST_GATE_JSON" 2>/dev/null || echo "unknown")"
  COST_BASIS="$(python3 -c 'import json,sys; e=json.loads(sys.argv[1]).get("estimate",{}); print(e.get("basis","unknown"))' "$COST_GATE_JSON" 2>/dev/null || echo "unknown")"
fi
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cost_gate_decision \
  "$(python3 -c 'import json,sys; print(json.dumps({"command":"z-audit","choice":"auto_proceed","reason":"soft_gate","estimated_tokens":json.loads(sys.argv[1]),"confidence":sys.argv[2],"basis":sys.argv[3]}))' \
     "${COST_ESTIMATED_TOKENS:-null}" "${COST_CONFIDENCE:-unknown}" "${COST_BASIS:-unknown}")"
```

Dispatch N parallel `/z-audit` sub-flows (one per chunk in `chunks`), all in a single message:

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement and skip all HEAVY sub-flow Agent() calls. Without subagent
     support the HEAVY path cannot proceed; default to MEDIUM mode. -->
Agent(
  subagent_type="orchestrator",
  description="z-audit sub-flow chunk <chunk-id>",
  prompt="Run /z-audit <sanitized $ARGUMENTS> --scope-from <abs path to ARCHIVE_SCOPE>#<chunk-id>\n\nParent run context (for logging and tracing only):\n- PARENT_RUN_ID: <interpolated value of $RUN>\n- PARENT_SLUG: <interpolated value of $Z_HARNESS_SLUG>\n- PARENT_ARCHIVE_SCOPE: <interpolated abs path to ARCHIVE_SCOPE>\n\nThis is a HEAVY fan-out sub-flow. The --scope-from argument is an ABSOLUTE PATH with fragment (not a bare chunk ID), so no bare-chunk-ID resolution is needed. The sub-flow resolves the chunk directly from the absolute SCOPE.json path provided."
)
```

Wait for all N sub-flows to return. Collect their returns.

After all sub-flows complete, dispatch `scope-reconciler-audit`:
```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement and skip the reconciler Agent() call. -->
Agent(
  subagent_type="scope-reconciler-audit",
  description="Reconcile HEAVY fanout for audit <slug>",
  prompt="host_run_id: <$RUN>\nchunks: <JSON array of {id, findings_path} for each completed sub-flow — findings_path is the per-chunk findings file produced by that sub-flow>\ntarget_slug: <slug>\naxis: <AXIS>\noutput_dir: <abs path to $Z_HARNESS_PLAN_DIR>"
)
```

Parse reconciler return using the same line-prefix + fenced-block pattern as scope-probe:

1. Read the reconciler return line-by-line.
2. Collect `KEY: VALUE` lines that appear **before** the first fenced block. Extract these routing fields: `STATUS`, `HOST_RUN_ID`, `REPORT_PATH`, `CHUNKS_DIR`, `UNIFIED_VERDICT`, `SUMMARY`.
3. The `COUNTS:` block is a multi-line indented YAML-like block — parse it as indented key-value pairs (`chunks_total`, `chunks_failed`, `findings_before_dedup`, `findings_after_dedup`, `elevated`, `dissent_groups`).
4. The `CHUNK_ARTIFACTS:` block is a YAML-like list with indented `dest:` and `source:` (or `content:`) fields — parse each list entry.
5. `REPORT_CONTENT:` is the label for a fenced markdown block containing the full REPORT.md text. Extract the content between the opening and closing fence markers (the fenced block immediately following `REPORT_CONTENT:`).

Write REPORT.md from the extracted `REPORT_CONTENT` fenced block:
```bash
# Write the extracted fenced block content (without the fence markers themselves) to REPORT.md
python3 -c "import sys; open(sys.argv[1],'w').write(sys.argv[2])" \
  "$Z_HARNESS_PLAN_DIR/REPORT.md" "<extracted REPORT_CONTENT fenced block body>"
```

Write each chunk artifact per the parsed `CHUNK_ARTIFACTS:` list. Before any write, validate paths:

```python
import os, sys

chunks_dir = os.path.join(Z_HARNESS_PLAN_DIR, "chunks")
# Allowed output roots built dynamically from the reconciler's chunks input.
# Each chunk carries a findings_path that lives in the sub-flow's own archive
# directory, which is OUTSIDE the parent's Z_HARNESS_PLAN_DIR. Extract the
# directory part of each findings_path and add it to allowed_source_roots so
# that legitimate per-chunk findings files are not silently rejected.
allowed_source_roots = [Z_HARNESS_PLAN_DIR] + [
    os.path.dirname(chunk["findings_path"])
    for chunk in chunks          # `chunks` is the reconciler-supplied chunks array
    if chunk.get("findings_path")
]

def validate_chunk_artifact(dest, source=None):
    # Reject any dest that is not under chunks_dir
    dest_abs = os.path.realpath(dest)
    if not dest_abs.startswith(os.path.realpath(chunks_dir) + os.sep):
        raise ValueError(f"CHUNK_ARTIFACTS dest outside allowed dir: {dest}")
    # Reject any dest with '..' components before realpath resolution
    if ".." in dest.split(os.sep):
        raise ValueError(f"CHUNK_ARTIFACTS dest contains '..': {dest}")
    if source is not None:
        # Reject source paths with '..'
        if ".." in source.split(os.sep):
            raise ValueError(f"CHUNK_ARTIFACTS source contains '..': {source}")
        # Reject source that is absolute but outside all allowed roots
        source_abs = os.path.realpath(source)
        if not any(source_abs.startswith(os.path.realpath(r) + os.sep)
                   for r in allowed_source_roots):
            raise ValueError(f"CHUNK_ARTIFACTS source outside allowed roots: {source}")
```

If validation fails for any entry, log a `scope_artifact_rejected` event with the reason and skip that entry. Do not abort the entire artifact write.

- For entries with `source` (after validation): copy the source file to `dest`.
- For entries with `content` (after `dest` validation): write the content string to `dest`.

Log event `scope_fanout_reconciled` using fields parsed from the line-prefix headers:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_fanout_reconciled \
  "$(python3 -c "
import json, sys
unified_verdict = sys.argv[1]
chunks_total = int(sys.argv[2])
chunks_failed = int(sys.argv[3])
findings_after_dedup = int(sys.argv[4])
print(json.dumps({'unified_verdict': unified_verdict, 'chunks_total': chunks_total, 'chunks_failed': chunks_failed, 'findings_after_dedup': findings_after_dedup}))
" "$UNIFIED_VERDICT" "$COUNTS_CHUNKS_TOTAL" "$COUNTS_CHUNKS_FAILED" "$COUNTS_FINDINGS_AFTER_DEDUP")"
```

**After HEAVY reconciliation: skip BOTH Phase 2 (standard auditor dispatch) AND Phase 3 (merge findings). The per-chunk sub-flows have already performed auditing; the reconciler has already produced REPORT.md. Proceed directly to Phase 4 (Bundled cross-LLM consult on the already-written REPORT.md), then Phase 5 (Promote to TASKS.md), etc.**

The findings-*.md files that Phase 3 would normally expect are NEVER written in the HEAVY path. Phase 3 must be skipped entirely — it will fail if attempted because those files do not exist. Phase 4 reads REPORT.md, which the reconciler has already written to `$Z_HARNESS_PLAN_DIR/REPORT.md`.

**HEAVY reconciler failure fallback:** If `scope-reconciler-audit` returns `STATUS: unable_to_complete`:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_fanout_reconciled \
  '{"status":"reconciler_failed","fallback":"concatenated_chunks"}'
```
Write a `REPORT.md` with `## Reconciliation failed — raw chunks below` as the header, then concatenate each chunk's findings file verbatim under `## Chunk: <chunk-id>` headings. Skip Phase 2 and Phase 3. Continue to Phase 4.

## Auto-bail thresholds (check after Phase 4)

If the merged findings count exceeds:

- **>30 findings total**, OR
- **>10 CRITICAL/HIGH findings** (indicates structural problems, not point fixes)

→ STOP. Write `$BASE/escalation.md` summarizing the scope. Do not generate TASKS.md. Per the FINALIZE_STATUS rule, execute **Run Brief — halt finalize** (below) with reason `auto-bail: findings exceed threshold`.

## Phase 1 — Pre-flight scoping

If `SCOPE_HINT` is set (from `--scope-from`), use `SCOPE_HINT` as the resolved target — do not re-derive the target from `$ARGUMENTS`. Skip the target confirmation step.

1. **Dimensions** — multi-select (≥1 required):

   **SCOPE check is first — before any other dimension-selection logic.** Check `$Z_HARNESS_PLAN_DIR/SCOPE-audit.json` (the live SCOPE file written by Phase 0). If it exists for this run (`last_run_id` matches `$RUN`) AND `mode` is `LIGHT` AND `dimensions_hint` is a non-empty array:
   - Auto-confirm the `dimensions_hint` list. Do NOT ask the user which dimensions to audit. Do NOT apply the "$ARGUMENTS named dimensions" shortcut below. Proceed as if the user selected those dimensions.
   - Inform the user: "Phase 0 scope probe suggested dimensions: <dimensions_hint list>. Proceeding with those."

   <!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the dimensions
        selection question via their native channel when no auto-resolved dimensions
        are available. Silent omission is forbidden. -->
   **Only if `SCOPE-audit.json` does not exist, `last_run_id` does not match, `mode` is not `LIGHT`, or `dimensions_hint` is absent/empty:** check whether `$ARGUMENTS` supplied a target + the user already named dimensions in prose. If dimensions are named in `$ARGUMENTS`, use those. Otherwise use `AskUserQuestion` to collect:
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

### Phase 2a — Resolve auditor personas (DIVERGENT site)

**Gated on `personas.audit` (default `true`). When the knob is OFF this entire block is a no-op** — every `DIM_*_PERSONA_PREFIX` stays empty and the dispatch in Phase 2b is byte-identical to the pre-feature single-prompt per dimension (no draw, no prefix, no `persona_bound` event). When ON, draw up to 4 **distinct** `audit_persona` personas and prepend one per dimension auditor — persona diversity layered on top of dimension-specific instructions.

The 4 fixed dimensions and their positional slots are: `correctness` (slot 0), `perf` (slot 1), `cleanliness` (slot 2), `design` (slot 3).

```bash
PLUGIN="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}"
AUDIT_PERSONAS="$(python3 "$PLUGIN/scripts/config.py" get personas.audit 2>/dev/null || echo true)"

# Vanilla defaults: empty prefix for all four dimension slots. Knob OFF leaves
# these untouched, so 2b dispatch is identical to the pre-persona behavior.
CORRECTNESS_PERSONA_PREFIX=""; CORRECTNESS_PERSONA_NAME=""; CORRECTNESS_DRAW_ID=""
PERF_PERSONA_PREFIX="";        PERF_PERSONA_NAME="";        PERF_DRAW_ID=""
CLEANLINESS_PERSONA_PREFIX=""; CLEANLINESS_PERSONA_NAME=""; CLEANLINESS_DRAW_ID=""
DESIGN_PERSONA_PREFIX="";      DESIGN_PERSONA_NAME="";      DESIGN_DRAW_ID=""

if [ "$AUDIT_PERSONAS" = "true" ]; then
  # Draw up to 4 distinct audit_persona personas. GRACEFUL DEGRADATION: if the
  # audit_persona pool has fewer than 4 members, the subcommand returns a shorter
  # array (or [] when empty) and exits 0 — never exits non-zero. Unfilled slots
  # stay vanilla (empty prefix).
  AUDIT_PERSONAS_JSON=$(python3 "$PLUGIN/scripts/resolve-persona.py" \
    random-distinct-for-role audit_persona --count=4 \
    2>>"$BASE/archive/$RUN/persona-draw.log")

  # Positional bind: [0]->correctness, [1]->perf, [2]->cleanliness, [3]->design.
  # `// ""` yields an empty string for absent indices under underflow.
  for slot in 0:CORRECTNESS 1:PERF 2:CLEANLINESS 3:DESIGN; do
    idx="${slot%%:*}"; dim="${slot##*:}"
    name=$(echo "$AUDIT_PERSONAS_JSON" | jq -r ".[$idx].persona // \"\"")
    path=$(echo "$AUDIT_PERSONAS_JSON" | jq -r ".[$idx].persona_body_path // \"\"")
    draw=$(echo "$AUDIT_PERSONAS_JSON" | jq -r ".[$idx].draw_id // \"\"")
    [ -z "$name" ] && continue   # underflow slot — leave vanilla
    # prepend_persona(path, "") strips frontmatter; re-append blank-line separator
    # because command substitution strips trailing newlines.
    prefix="$(python3 "$PLUGIN/runtime/dispatch/persona_prompt.py" "$path" "" 2>/dev/null | head -c 4096 || true)"
    [ -n "$prefix" ] && prefix="${prefix}

"
    printf -v "${dim}_PERSONA_NAME" '%s' "$name"
    printf -v "${dim}_PERSONA_PREFIX" '%s' "$prefix"
    printf -v "${dim}_DRAW_ID" '%s' "$draw"
  done

  # Emit persona_bound per auditor that received a persona (attribution;
  # no outcome tracking — auditors have no measurable terminal).
  # Skip any vanilla slot and skip the whole step when the knob is OFF.
  for slot in correctness:CORRECTNESS perf:PERF cleanliness:CLEANLINESS design:DESIGN; do
    dim="${slot%%:*}"; who="${slot##*:}"
    eval "pname=\$${who}_PERSONA_NAME"; eval "pdraw=\$${who}_DRAW_ID"
    [ -z "$pname" ] && continue
    bash "$PLUGIN/scripts/log-event.sh" "$RUN" persona_bound \
      "$(python3 -c 'import json,sys; print(json.dumps({
        "command":"z-audit","role":"audit_persona",
        "dimension":sys.argv[1],"persona_id":sys.argv[2],
        "draw_id":sys.argv[3],"selection_source":"random_role_pool_distinct"
      }))' "$dim" "$pname" "$pdraw")"
  done
fi
```

### Phase 2b — Dispatch

Spawn one `auditor` subagent **per selected dimension**, in parallel, in a single message:

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip all auditor Agent() calls. The audit
     cannot proceed without subagent support. -->
Agent(
  subagent_type="auditor",
  description="<dim> audit of <slug>",
  prompt="<DIM_PERSONA_PREFIX>DIMENSION: <dim>\nTARGET: <abs path> — <one-line description>\nRUBRIC_PATH: <abs path or empty>\n$BASE: <abs path to $BASE>\nrelevant_docs:\n  - <doc1>\n  - <doc2>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]\n\nFollow your agent definition. Emit findings to $BASE/findings-<dim>.md and return STATUS + COUNTS + VERDICT."
)
```

Each `<DIM_PERSONA_PREFIX>` is the persona body for that dimension followed by a blank line (from Phase 2a), or **empty** when that dimension drew no persona (underflow slot) or the `personas.audit` knob is OFF — in the empty case the prompt is byte-identical to the pre-persona dispatch.

Each auditor writes `$BASE/findings-<dim>.md` and returns a structured summary. Collect all returns.

<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the auditor
     failure gate (retry / skip / abort) via their native channel.
     Silent omission is forbidden. -->
**If any auditor returns `unable_to_complete`** — surface the reason via `AskUserQuestion`: retry that dimension / skip it / abort the audit. If the user chooses **abort the audit**, execute **Run Brief — halt finalize** with reason `auditor unable_to_complete`.

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

### Phase 4a — Measured persona advisory arm (CONVERGENT site)

**This arm is ADDITIVE and ADVISORY only. The neutral consult's synthesis (Phase 4b) is the decision of record. The persona arm's output is NEVER folded into the Phase 4b synthesis.**

Read the `personas.consult_eval` knob:

```bash
PLUGIN="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}"
CONSULT_EVAL="$(python3 "$PLUGIN/scripts/config.py" get personas.consult_eval 2>/dev/null || echo false)"
```

**When `CONSULT_EVAL` is `true`:** draw ONE `consultant` persona and dispatch an additional advisory arm IN PARALLEL with the two neutral consultants in Phase 4b (include it in the same parallel message):

```bash
# Draw one consultant persona. Graceful underflow: if the pool is empty,
# the command returns [] and exits 0 — skip the advisory arm entirely.
ADVISORY_PERSONA_JSON=$(python3 "$PLUGIN/scripts/resolve-persona.py" \
  random-distinct-for-role consultant --count=1 \
  2>>"$BASE/archive/$RUN/persona-draw.log")

ADVISORY_PERSONA_NAME=$(echo "$ADVISORY_PERSONA_JSON" | jq -r '.[0].persona // ""')
ADVISORY_PERSONA_PATH=$(echo "$ADVISORY_PERSONA_JSON" | jq -r '.[0].persona_body_path // ""')
ADVISORY_DRAW_ID=$(echo "$ADVISORY_PERSONA_JSON" | jq -r '.[0].draw_id // ""')

if [ -n "$ADVISORY_PERSONA_NAME" ]; then
  # Prepend persona body to the advisory prompt (strips frontmatter); re-append
  # blank-line separator because command substitution strips trailing newlines.
  ADVISORY_PREFIX="$(python3 "$PLUGIN/runtime/dispatch/persona_prompt.py" \
    "$ADVISORY_PERSONA_PATH" "" 2>/dev/null | head -c 4096 || true)"
  [ -n "$ADVISORY_PREFIX" ] && ADVISORY_PREFIX="${ADVISORY_PREFIX}

"

  # Emit persona_bound for the advisory arm (attribution; no outcome tracking).
  bash "$PLUGIN/scripts/log-event.sh" "$RUN" persona_bound \
    "$(python3 -c 'import json,sys; print(json.dumps({
      "command":"z-audit","role":"consultant",
      "arm":"advisory","persona_id":sys.argv[1],
      "draw_id":sys.argv[2],"selection_source":"random_role_pool"
    }))' "$ADVISORY_PERSONA_NAME" "$ADVISORY_DRAW_ID")"
fi
```

### Phase 4b — Neutral consult dispatch

Spawn both neutral consultants in parallel against `REPORT.md`. When `CONSULT_EVAL` is `true` and `ADVISORY_PERSONA_NAME` is non-empty, include the advisory arm as a **third Agent() call in the same parallel message**:

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip both consultant Agent() calls. Phase 4
     cannot complete without subagent support; document the gap and proceed. -->
Agent(
  subagent_type="consultant-primary",
  description="Audit findings review (Gemini) for <slug>",
  prompt="MODE: audit-review\n\nA target has been audited across <dimensions>. Here is the full REPORT:\n\n<paste REPORT.md>\n\nTwo asks:\n1. What significant findings are MISSING — issues the dimension auditors should have caught but didn't?\n2. Which listed findings are TRIVIAL or speculative and should be dropped before promotion to TASKS.md?\n\nBe specific. Cite path:line. Severity-rank any additions.\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
Agent(
  subagent_type="consultant-secondary",
  description="Audit findings review (Codex) for <slug>",
  prompt="MODE: audit-review\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
```

**When `CONSULT_EVAL` is `true` and `ADVISORY_PERSONA_NAME` is non-empty**, include this third Agent() call IN THE SAME parallel message as the two neutral consultants above:

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to the user and skip the advisory Agent() call when personas.consult_eval is on. The advisory arm is advisory only — skipping it does not affect the neutral synthesis. -->
```
Agent(
  subagent_type="consultant-primary",
  description="Advisory persona consult for audit <slug>",
  prompt="<ADVISORY_PREFIX>MODE: audit-review\n\n<same prompt body as neutral arms>"
)
```

**Capture the advisory arm's output in a separate variable** (e.g. `ADVISORY_RECOMMENDATION`). Do NOT pass it to the synthesis step below. After Phase 4b returns, log the advisory recommendation as a dedicated telemetry event:

```bash
if [ -n "$ADVISORY_PERSONA_NAME" ]; then
  bash "$PLUGIN/scripts/log-event.sh" "$RUN" persona_advisory_recommendation \
    "$(python3 -c 'import json,sys; print(json.dumps({
      "command":"z-audit","phase":4,
      "persona_id":sys.argv[1],"draw_id":sys.argv[2],
      "recommendation": sys.argv[3][:2000]
    }))' "$ADVISORY_PERSONA_NAME" "$ADVISORY_DRAW_ID" "$ADVISORY_RECOMMENDATION")"
fi
```

**Neutral-authority contract (mechanical, load-bearing):**
- The neutral consult's synthesis is the decision of record.
- The persona advisory arm's recommendation is emitted under `persona_advisory_recommendation` — it is NEVER merged into the synthesis below.
- No prose path in the synthesis step may instruct the orchestrator to read the advisory arm's output into the final REPORT.md additions/drops.
- **Acceptance criterion (mock-disagreement):** If the persona advisory arm recommends dropping finding F and the two neutral arms both recommend keeping F, the synthesis keeps F unchanged. The `persona_advisory_recommendation` event records the drop recommendation for later analysis.

**When `CONSULT_EVAL` is `false` (default) or `ADVISORY_PERSONA_NAME` is empty (underflow):** skip the advisory arm entirely. The Phase 4b dispatch is byte-identical to the pre-feature two-arm neutral consult. No draw event, no prefix, no `persona_bound`, no `persona_advisory_recommendation`.

Both transcripts archive themselves under `$BASE/archive/$RUN/transcripts/`.

**When both neutral arms return (advisory arm output is captured separately):**

1. For each addition: apply the "one reason this might be wrong" check before accepting.
2. For each suggested drop: confirm by re-reading the cited code.
3. Update `REPORT.md` with `## Consult additions` and `## Consult drops` sections noting what changed and which consultant flagged it.

**Check auto-bail thresholds now** (see top). If the post-consult count exceeds the bail thresholds, escalate to `/z-plan`. Execute **Run Brief — halt finalize** with reason `auto-bail: post-consult findings exceed threshold`.

## Phase 5 — Promote to TASKS.md

Only actionable findings go into TASKS.md. An observation that has no clear fix stays in REPORT.md.

Write `$BASE/TASKS.md` in the **exact format `/z-execute` consumes** (mirror `agents/implementer.md` shape):

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

**Note in `$BASE/SPEC.md`:** `/z-execute` will read `$BASE/SPEC.md`. Audits don't produce a SPEC, but the implementer reads it. Write a minimal `$BASE/SPEC.md`:

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

This three-file set (SPEC.md / PLAN.md / TASKS.md) is what `/z-execute` requires.

## Phase 6 — Codex safety gate on TASKS.md

Spawn the reviewer against the audit-produced TASKS.md (the diff in this case is the TASKS.md itself):

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip the reviewer Agent() call. The safety
     gate cannot run without subagent support; document the gap. -->
Agent(
  subagent_type="reviewer",
  description="Codex review of audit TASKS for <slug>",
  prompt="task id: <slug>-audit-tasks\ntask description: review the audit-produced TASKS.md for soundness — would executing these tasks make the target better or risk regression?\nacceptance criteria: every task addresses a real finding in REPORT.md with a verifiable acceptance line\ndiff.patch path: (n/a — review the file directly)\nchanged files: <abs path to $BASE/TASKS.md>\nrelevant_docs: <any docs/llm paths from Setup step 7>\n$BASE: <abs path to $BASE>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]\n\nFlag: tasks that would regress invariants, tasks with vague acceptance, severity inflation, scope creep beyond the cited finding."
)
```

Parse the return (capped at 8 KB):
<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the reviewer
     second-failure gate via their native channel. Silent omission is forbidden. -->
- **Blockers** → re-edit the affected TASKS.md entries; re-run review once. Second failure → halt with `AskUserQuestion`.
- **Majors** → fix in place, then accept.
- **No blockers/majors** → accept.

## Phase 7 — Present + finalize

Set run-brief env and host sections **before** the shared fragment (classify is `unknown` until `audit_run_end`; preset `status: complete` per PLAN invariant #1):

```bash
CURRENT_ARCHIVE_DIR="$BASE/archive/$RUN"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="$BASE/REPORT.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS=""
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"

# Outcome + next (success path)
if [[ "$N_TASKS" -gt 0 ]]; then
  _RB_NEXT_CMD="/z-execute"
  _RB_NEXT_LABEL="Run /z-execute on audit tasks"
else
  _RB_NEXT_CMD="/z-plan"
  _RB_NEXT_LABEL="Escalate structural findings via /z-plan"
fi
bash "$RB_SH" set-section --run "$RUN" --section outcome \
  --value "Audit complete: ${N_FINDINGS} findings, ${N_TASKS} tasks across ${DIMS}"
bash "$RB_SH" set-section --run "$RUN" --section next --json /dev/stdin <<JSON
{"label": "${_RB_NEXT_LABEL}", "command": "${_RB_NEXT_CMD}"}
JSON

# Pre-seed approach when REPORT.md is prose-only (no extractable list bullets)
if [[ -f "$RUN_BRIEF_ARTIFACT" ]]; then
  _RB_APPROACH_N="$(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rrb", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(len(mod.extract_approach_bullets(sys.argv[2])))
' "$RB_PY" "$RUN_BRIEF_ARTIFACT")"
  if [[ "$_RB_APPROACH_N" -gt 0 ]]; then
    bash "$RB_SH" set-section --run "$RUN" --section approach --file "$RUN_BRIEF_ARTIFACT" || true
  else
    _RB_SEED="$CURRENT_ARCHIVE_DIR/run-brief-approach-seed.md"
    printf '%s\n' \
      "- Audited dimensions: ${DIMS}" \
      "- ${N_FINDINGS} findings documented in REPORT.md" \
      "- ${N_TASKS} tasks promoted to TASKS.md" \
      > "$_RB_SEED"
    bash "$RB_SH" set-section --run "$RUN" --section approach --file "$_RB_SEED" || true
  fi
fi
bash "$RB_SH" set-section --run "$RUN" --section status --value "complete"
```

<!-- include: _fragments/run-brief-finalize.md -->

Log run end (after brief `--require` gate):
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" audit_run_end \
  "$(printf '{"command":"z-audit","status":"complete","findings":%d,"tasks":%d,"dimensions":"%s"}' "$N_FINDINGS" "$N_TASKS" "$DIMS")"
```

**Deregister this run** from the active-plan registry (best-effort, non-fatal). Per the FINALIZE_STATUS rule (Setup step 6): normal completion deregisters with `complete` only when brief `--require` passed.
```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
  --run-id "$RUN" --status "${FINALIZE_STATUS:-complete}" || true   # CLI self-logs registry_error on failure
```

## Run Brief — halt finalize

Before `deregister --status aborted` on any halt after `run-brief.sh init` (unless register failed — no deregister). Substitute `<reason>` in the outcome line. When `REPORT.md` is missing, the shared fragment auto-downgrades to **lite** (Intent + Outcome + Next).

```bash
CURRENT_ARCHIVE_DIR="$BASE/archive/$RUN"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="$BASE/REPORT.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS=""
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
bash "$RB_SH" set-section --run "$RUN" --section next --json /dev/stdin <<'JSON'
{"label": "Review audit status and retry or escalate", "command": null}
JSON
```

<!-- include: _fragments/run-brief-finalize.md -->

```bash
FINALIZE_STATUS=aborted
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
  --run-id "$RUN" --status aborted 2>/dev/null || true
```

## Telemetry reference

| Event kind | When / meaning | Required fields |
|---|---|---|
| `audit_run_start` | Audit run begins | version fields, `target`, `command` |
| `audit_run_end` | Audit run completes | `command`, `status`, `findings`, `tasks`, `dimensions` |
| `scope_from_resolved` | `--scope-from` chunk resolved successfully | `chunk_id`, `scope_hint`, `parent_scope_json` |
| `scope_probe_start` | Scope-probe Agent dispatched | `axis_taxonomy` |
| `scope_probe_classified` | Scope-probe returned `STATUS: classified` | `status`, `mode`, `axis`, `confidence`, `reason_codes`, `reason`, `seams_counted`, `candidates_walked` |
| `scope_probe_malformed` | Scope-probe return failed to parse | `reason`, `raw_truncated` |
| `scope_probe_skipped_fast_path` | Single-file target auto-classified LIGHT, scope-probe Agent skipped | `command` (`z-audit`), `target`, `arg_len` |
| `scope_artifact_rejected` | A CHUNK_ARTIFACTS path failed validation | `reason`, `dest` |
| `scope_fanout_dispatched` | HEAVY mode: N sub-flows launched | `chunk_count`, `chunks`, `axis` |
| `scope_fanout_reconciled` | HEAVY mode: reconciler finished | `unified_verdict`, `chunks_total`, `chunks_failed`, `findings_after_dedup` |
| `persona_bound` | Persona bound to an auditor (Phase 2a) or advisory consult arm (Phase 4a) | `command`, `role`, `dimension` (auditors only), `arm` (advisory arm only), `persona_id`, `draw_id`, `selection_source` |
| `persona_advisory_recommendation` | Advisory consult arm's recommendation logged separately (Phase 4b) | `command`, `phase`, `persona_id`, `draw_id`, `recommendation` |

## Decision emission (standing instruction)

After **any** `AskUserQuestion` resolves, emit a normalized decision event:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-decision.sh" \
  "$RUN" "<question_id>" "<chosen_label>" \
  --options '["<opt1>","<opt2>",...]' \
  [--tentative "<recommended_option>"]
```

- `<question_id>` — stable kebab-case identifier for this decision point (e.g. `workflow.implement_all_proceed`, `workflow.slug_confirm`).
- `<chosen_label>` — the option label the user selected, verbatim.
- `--options` — full list of offered option labels as a JSON array.
- `--tentative` — the orchestrator's recommended option label; omit when the orchestrator had no recommendation.

Emission is gated by `axioms.auto_extract_post_run` (default `true`); when `false`, the script exits silently — no guard is needed here. Do **not** modify existing structured gate events (`cost_gate_decision`, `critique_failure_decision`, `map_collision_decision`, `shared_concerns_ack_override`); those are normalized separately by the extractor. This emission **records signal only** — it never approves, overrides, or influences any decision (proposes-only invariant).

---

## Hard rules

- **Read-only.** Never edit the target. Ever.
- **Never skip the codex safety gate** on the produced TASKS.md.
- **Always emit cross-LLM consult** in Phase 4 — both Gemini and Codex, in parallel.
- **One auditor per dimension, in parallel.** Never serialize.
- **TASKS.md format must match what `/z-execute` consumes** — otherwise the audit is a dead-end artifact.
- **No emojis** anywhere in artifacts.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Setup doc-fetcher Agent(); Phase 0 scope-probe, HEAVY orchestrator sub-flows, and scope-reconciler-audit Agent() calls; Phase 2b auditor Agent() calls (persona-prefixed when `personas.audit` on); Phase 4b consultant-primary and consultant-secondary Agent() calls; Phase 4b advisory persona arm Agent() call (when `personas.consult_eval` on and persona drawn); Phase 6 reviewer Agent() call |
| `ask_user` | yes | Empty arguments gate; Setup slug confirmation if non-obvious; Phase 1 dimensions selection; Phase 2b auditor unable_to_complete gate; Phase 6 reviewer second-failure gate |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
