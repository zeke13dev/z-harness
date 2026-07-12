---
name: z-audit
description: Audit a target component across one or more dimensions (correctness / perf / cleanliness / design). Pre-flight scopes (target, dimensions, optional rubric file), spawns one auditor subagent per dimension in parallel, runs bundled Gemini+Codex consult on findings, emits REPORT.md + TASKS.md under $Z_HARNESS_PLAN_DIR-audit/ in the exact shape /z-execute consumes. Read-only — never edits the target.
argument-hint: "<target path or component name> [--scope-from <chunk-spec>]"
audience: user
driver_features_required: [subagent, ask_user]
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

## Shared context checkpoint hook/check contract

Every durable-boundary checkpoint seam is one call to `scripts/checkpoint-seam.sh` (SKILL-STYLE.md §2 — thin wrapper over `check-compaction.sh` + `write-clear-checkpoint.sh`; never write `handoff.json` directly). Wrapped here since this run has five call sites:

```bash
audit_checkpoint_seam() {
  local seam_id="$1" artifact="$2" next_step="$3"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/checkpoint-seam.sh" \
    "$seam_id" "$artifact" "/z-audit <target>" \
    --producer z-audit --next-step "$next_step"
  local rc=$?
  case "$rc" in
    0) return 0 ;;  # below threshold, or already fast-forwarded — continue
    1) exit 0 ;;     # new checkpoint written — pause here, not an error; next invocation resumes
    2) # Execute Run Brief — halt finalize with reason "context pressure estimate failed in strict mode at $seam_id", then exit 1.
       exit 1 ;;
  esac
}
```

A skill contributes only its seam TABLE — registered durable seams:

| Seam id | When it runs | Durable artifact | Next step |
|---------|--------------|------------------|-----------|
| `audit-phase4-pre-consult` | after `REPORT.md` exists, immediately before Phase 4 consultant dispatch | `$BASE/REPORT.md` | resume at Phase 4 consultant dispatch |
| `audit-phase4-post-consult` | after consultant transcripts are archived and consult additions/drops are appended | `$BASE/REPORT.md` | resume at post-consult auto-bail and promotion |
| `audit-phase5-pre-promotion` | before generating audit `TASKS.md`/`SPEC.md`/`PLAN.md` from accepted findings | `$BASE/REPORT.md` | resume at Phase 5 promotion |
| `audit-phase6-pre-review` | after audit `TASKS.md`/`SPEC.md`/`PLAN.md` are durable, before reviewer dispatch | `$BASE/TASKS.md` | resume at Phase 6 safety gate |
| `audit-phase7-pre-user-report` | after reviewer acceptance, before run-brief/final user-facing report generation | `$BASE/REPORT.md` | resume at Phase 7 finalize |

Skipped candidate seams: no check before Phase 2 auditor dispatch (no durable findings artifact yet), no check while auditors or consultants are in flight, no check between re-reading cited code and applying a consult decision, and no check after a run-ending halt because halt finalize owns that terminal state.

## --scope-from flag handling (parsed BEFORE Setup)

Parse `$ARGUMENTS` for `--scope-from <chunk-spec>` **immediately — before slug derivation, doc-fetcher, or preflight ceremony**. This ordering ensures recursive sub-flows do not pollute the parent run's slug or events.

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
2. **Derive slug** — short kebab-case like `audit-<component>` (e.g. target `strategies/kxbtc15m_fade_extremes` → `audit-kxbtc15m`). Confirm via `AskUserQuestion` if non-obvious. Check `bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" all_plan_slugs` first for collisions. Set `Z_HARNESS_SLUG=<slug>-audit`.

3. **Preflight ceremony (single call, read-only).** `scripts/z-preflight.sh` owns resolve/session-id/RUN-stamp/register/run-brief-init/run_start/kernel-resolve, in that fixed order (contract: script header; LEDGER T005). `/z-audit` never edits the target — only its own `REPORT.md`/`TASKS.md` artifacts under `$Z_HARNESS_PLAN_DIR/` — so it runs the lifecycle **minus the claim** (`--no-claim`; SKILL-STYLE.md §2). This also preserves the original no-lock behavior: `/z-audit` has never called `plan-claim.sh`, including across HEAVY fan-out sub-flows that re-derive the same slug from the same `$ARGUMENTS` and would otherwise self-contend.
   ```bash
   AUDIT_INTENT="$(python3 -c 'import sys; t=sys.argv[1].strip(); print(("Audit: "+t)[:240] if t else "Audit target component")' "<sanitized $ARGUMENTS>")"
   # Capture BEFORE eval — $? after eval loses the script's exit-code contract.
   PREFLIGHT_OUT="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-preflight.sh" \
     --command /z-audit --slug "$Z_HARNESS_SLUG" --phase audit --no-claim \
     --intent "$AUDIT_INTENT")"
   PREFLIGHT_RC=$?
   [ "$PREFLIGHT_RC" -eq 0 ] && eval "$PREFLIGHT_OUT"
   ```
   `--no-claim` skips the claim step entirely — a nonzero `PREFLIGHT_RC` here means a genuine setup failure (bad invocation or path resolution), not contention: surface the stderr diagnostic and exit, nothing was ever created or registered. On success, `RUN`, `Z_HARNESS_PLAN_DIR`, `CURRENT_ARCHIVE_DIR`, `Z_HARNESS_SESSION_ID`, `REG_RC`, and `KERNEL_PATH` are exported (script header is the source of truth). Run-brief is initialized as part of this call — registry `/z-audit`, profile `full`, artifact `REPORT.md`:
   ```bash
   export RUN_BRIEF_PROFILE=full
   export RUN_BRIEF_ARTIFACT="$Z_HARNESS_PLAN_DIR/REPORT.md"
   export RUN_BRIEF_ARTIFACT_FALLBACKS=""
   ```
   When `KERNEL_PATH` is non-empty, inject `kernel_path: <KERNEL_PATH>` as a line in the `Agent(prompt=...)` of every behavioral-agent dispatch in this run (auditor, consultant-primary, consultant-secondary, reviewer). Omit the line entirely when `KERNEL_PATH` is empty — the agent's static fallback handles self-resolution in that case. Do NOT inject kernel content — inject the path string only.

   **Register-failure menu** (this command's deviation from the standard menu documented once in the `z-preflight.sh` header, SKILL-STYLE.md §2 — contention/corrupt-lock exits cannot occur under `--no-claim`). Graduated failure policy — never silent-continue on failure:
   - `REG_RC == 0` → registered; proceed.
   - `REG_RC == 3` (no record written) → emit `registry_error` event; interactive → `AskUserQuestion` proceed/abort; unattended → proceed+log (or halt if `Z_HARNESS_STRICT_OVERLAP=1`). No deregister on abort (no record).
   - Any OTHER nonzero → treat as `REG_RC == 3`.
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" registry_error \
     "$(printf '{"op":"register","run_id":"%s","rc":%d}' "$RUN" "$REG_RC")"
   ```

4. **Log audit run start** (domain-specific field the generic wrapper `run_start` event doesn't carry):
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["target"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<sanitized $ARGUMENTS>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" audit_run_start "$START_PAYLOAD"
   ```

5. Notification policy: see [docs/human/config.md](docs/human/config.md) (notify.level key).
6. **Artifact Scout preflight (skipped for `--scope-from` children):**
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

7. If `docs/llm/INDEX.json` exists → dispatch `doc-fetcher` (Haiku) to get the concept list overlapping the audit target. Do NOT read INDEX.json or per-concept JSONs from main thread.
   ```
   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
        requirement and skip if unavailable. Audit proceeds without doc grounding. -->
   Agent(subagent_type="doc-fetcher",
         description="Doc context for audit <slug>",
         prompt="query: which concepts cover <audit target paths>?\nrepo_root: <abs path>\ndepth: summary")
   ```
   The orchestrator captures the returned concept slugs and passes the corresponding `docs/llm/<slug>.json` paths to auditors as `relevant_docs` (the auditors then read them themselves — they're fresh-context already).

`$BASE = $Z_HARNESS_PLAN_DIR/`.

**Every controlled exit past this point funnels through `scripts/z-teardown.sh`** (SKILL-STYLE.md §2, ONE-FUNNEL) — success through Phase 7, everything else through **Run Brief — halt finalize** below. Never a bespoke cleanup path, and never an `exit` past the funnel (the sole exception is a checkpoint-seam PAUSE, which is not an exit).

## Phase 0 — Scope probe

**Check `SKIP_PHASE_0` first.** If `SKIP_PHASE_0=true` (set by `--scope-from` flag handling above), skip this entire section immediately and proceed to Phase 1. Do not dispatch scope-probe, do not write SCOPE files, do not log scope_probe_* events.

If `SKIP_PHASE_0` is not set, execute the following:

### Step 0a — Fast-path check (single-file target)

Before dispatching scope-probe, check whether the target auto-qualifies for LIGHT classification (single existing file, no glob metacharacters, short argument) — mechanical, delegated to `scripts/audit-scope-probe.sh` (SKILL-STYLE.md §2 extraction; script header owns the exact classification rule and the fast-path-check output contract):

```bash
FAST_PATH_OUT="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/audit-scope-probe.sh" \
  fast-path-check --arg "<sanitized $ARGUMENTS>" --run "$RUN")"
eval "$FAST_PATH_OUT"
```

On qualify, the script has already logged `scope_probe_skipped_fast_path` and the eval exports `SCOPE_FAST_PATH=1` plus the LIGHT classification (`MODE=LIGHT`, `AXIS=none`, `CONFIDENCE=high`, `REASON_CODES=fast_path_single_file`, `REASON`, `chunks=[]`, `seams_counted=0`, `candidates_walked=0`). On non-qualify, only `SCOPE_FAST_PATH=0` is exported — no event, no other variables, no scope-probe Agent dispatched.

If `SCOPE_FAST_PATH=1`, skip Steps 0.1 and 0.2 entirely and jump to Step 0.3 with the classification exported above (`dimensions_hint` is still derived fresh in Step 0.3's LIGHT branch, per normal flow). If `SCOPE_FAST_PATH=0`, run Steps 0.1 and 0.2 below (multi-file / glob / large-arg path).

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

### Step 0.3 — Write SCOPE.json (archive-then-live; mechanical, delegated to `scripts/audit-scope-probe.sh`)

**If `MODE` is `LIGHT`: derive `dimensions_hint` first (before any write).** Inspect the topic (sanitized `$ARGUMENTS`) and seam evidence: identify which of `correctness`, `perf`, `cleanliness`, `design` are most relevant. Typically a single-file, no-seam target narrows to 1–2 dimensions. Store the result in `DIMENSIONS_HINT_LIST` (a JSON array string, e.g. `["correctness","perf"]`).

Assemble and write both copies — archive first, then live, each an atomic tmp+rename (same order; prevents partial-overwrite on parallel runs) — with one call (script header owns the exact `SCOPE.json` shape: `host_command`, `slug`, `last_run_id`, `last_updated`, `mode`, `axis`, `confidence`, `reason_codes`, `chunks`, `seams_counted`, `candidates_walked`, `scope_probe_version`, plus `dimensions_hint` for LIGHT):

```bash
WRITE_SCOPE_ARGS=(
  --plan-dir "$Z_HARNESS_PLAN_DIR" --run "$RUN" --slug "$Z_HARNESS_SLUG"
  --mode "$MODE" --axis "$AXIS" --confidence "$CONFIDENCE"
  --reason-codes "$REASON_CODES" --chunks "$chunks"
  --seams-counted "$seams_counted" --candidates-walked "$candidates_walked"
)
[ "$MODE" = "LIGHT" ] && WRITE_SCOPE_ARGS+=(--dimensions-hint "$DIMENSIONS_HINT_LIST")
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/audit-scope-probe.sh" write-scope "${WRITE_SCOPE_ARGS[@]}"
WRITE_SCOPE_RC=$?
```

If `WRITE_SCOPE_RC` is nonzero, the write failed (archive assembly, archive write, or live write — script header's exit-code contract) — abort Phase 0 entirely. The live file was never written unless the archive copy succeeded first. Log event:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_classified \
  '{"status":"archive_write_failed","mode":"MEDIUM","note":"proceeding as MEDIUM"}'
```
Host proceeds as MEDIUM. Skip to Phase 1.

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

→ STOP. Write `$BASE/escalation.md` summarizing the scope. Do not generate TASKS.md. Execute **Run Brief — halt finalize** (below) with reason `auto-bail: findings exceed threshold`.

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

### Phase 2a — Dispatch

Spawn one `auditor` subagent **per selected dimension**, in parallel, in a single message:

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip all auditor Agent() calls. The audit
     cannot proceed without subagent support. -->
Agent(
  subagent_type="auditor",
  description="<dim> audit of <slug>",
  prompt="DIMENSION: <dim>\nTARGET: <abs path> — <one-line description>\nRUBRIC_PATH: <abs path or empty>\n$BASE: <abs path to $BASE>\nrelevant_docs:\n  - <doc1>\n  - <doc2>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]\n\nFollow your agent definition. Emit findings to $BASE/findings-<dim>.md and return STATUS + COUNTS + VERDICT."
)
```

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

Spawn both consultants in parallel against `REPORT.md`:

Before dispatching Phase 4 consultants:
```bash
audit_checkpoint_seam audit-phase4-pre-consult "$BASE/REPORT.md" "resume at Phase 4 consultant dispatch"
```

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

Both transcripts archive themselves under `$BASE/archive/$RUN/transcripts/`.


**When both consultants return:**

1. For each addition: apply the "one reason this might be wrong" check before accepting.
2. For each suggested drop: confirm by re-reading the cited code.
3. Update `REPORT.md` with `## Consult additions` and `## Consult drops` sections noting what changed and which consultant flagged it.

After `REPORT.md` has been updated with `## Consult additions` and `## Consult drops` from the neutral consult synthesis, checkpoint before auto-bail or promotion decisions:
```bash
audit_checkpoint_seam audit-phase4-post-consult "$BASE/REPORT.md" "resume at post-consult auto-bail and promotion"
```

**Check auto-bail thresholds now** (see top). If the post-consult count exceeds the bail thresholds, escalate to `/z-plan`. Execute **Run Brief — halt finalize** with reason `auto-bail: post-consult findings exceed threshold`.

Before generating promoted audit artifacts:
```bash
audit_checkpoint_seam audit-phase5-pre-promotion "$BASE/REPORT.md" "resume at Phase 5 promotion"
```

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

After `$BASE/TASKS.md`, `$BASE/SPEC.md`, and `$BASE/PLAN.md` are written, checkpoint before dispatching the reviewer:
```bash
audit_checkpoint_seam audit-phase6-pre-review "$BASE/TASKS.md" "resume at Phase 6 safety gate"
```

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

After the reviewer accepts the audit TASKS, checkpoint before run-brief/final user-facing report generation:
```bash
audit_checkpoint_seam audit-phase7-pre-user-report "$BASE/REPORT.md" "resume at Phase 7 finalize"
```

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

Log run end (after brief `--require` gate), then tear down through the one funnel (finalizes the brief a second time — idempotent — releases the never-held claim, deregisters, emits the generic `run_end`):
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" audit_run_end \
  "$(printf '{"command":"z-audit","status":"complete","findings":%d,"tasks":%d,"dimensions":"%s"}' "$N_FINDINGS" "$N_TASKS" "$DIMS")"
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
  --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-audit --status "${FINALIZE_STATUS:-complete}"
```

## Run Brief — halt finalize

Every terminal halt after Setup step 3's `z-preflight.sh` call has succeeded (i.e. `RUN` is exported) funnels through this same procedure — never a bespoke cleanup path (SKILL-STYLE.md §2). Substitute `<reason>` in the outcome line. When `REPORT.md` is missing, the shared fragment auto-downgrades to **lite** (Intent + Outcome + Next).

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
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
  --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-audit --status aborted
exit 1
```

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

Driver support requirements: see frontmatter `driver_features_required`. Non-supporting drivers **must surface and skip** any gated block — silent omission is forbidden. Each gated call site carries its own `<!-- RUNTIME-GATE: ... -->` comment immediately before the call; that is the single source of truth (SKILL-STYLE.md §1 — the closing conformance table is retired for rewritten skills).
