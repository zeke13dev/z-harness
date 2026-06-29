---
name: z-debug
disable-model-invocation: false
description: Heavy hypothesis-tournament debugging pipeline for the case where root cause is unknown. Two rounds of adversarial multi-LLM hypothesis generation (Claude + Codex + Gemini), discriminating-test matrix with consensus-first ranking + forced outlier carve-out, ordinal Bayesian scoring with orchestrator-assigned likelihoods, 3-5 isolation rounds, fix-gate requires highest posterior AND causal mechanism explaining all evidence. Single unified DEBUG.md artifact. Early gate recommends /z-fix if user already has a diagnosis.
argument-hint: <symptom description>
runtime: c1
driver_features_required:
  - subagent
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-debug`** — heavy hypothesis-tournament pipeline for an existing bug whose root cause is unknown. This is the discipline path. If the user already has a working hypothesis they want to ship a fix for, Phase 0 will redirect them to `/z-fix`.

Symptom (from `$ARGUMENTS`):

$ARGUMENTS

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the question
     "What's the symptom?" via their native channel. Silent omission is forbidden. -->
**If empty** — `AskUserQuestion`: "What's the symptom?" before proceeding.

## Setup

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the slug
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
   Resolve the kernel path exactly once here. When `KERNEL_PATH` is non-empty, inject `kernel_path: <KERNEL_PATH>` as a line in the `Agent(prompt=...)` of every behavioral-agent dispatch in this run (consultant-primary, consultant-secondary). Omit the line entirely when `KERNEL_PATH` is empty — the agent's static fallback handles self-resolution in that case. Do NOT inject kernel content — inject the path string only.

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

## Shared context checkpoint hook/check contract

`/z-debug` uses the reusable z-harness hook/check layer at every durable debug seam. It MUST NOT keep workflow-local checkpoint snippets, ack files, or direct `handoff.json` writes. Do not write `handoff.json` directly; call `scripts/check-compaction.sh` first and call `scripts/write-clear-checkpoint.sh` only when the shared check exits `1`.

Standard seam call pattern:

```bash
run_zdebug_compaction_seam() {
  local seam_id="$1" phase_name="$2" completed_artifact="$3" next_step="$4"
  local debug_md="$Z_HARNESS_PLAN_DIR/DEBUG.md"
  export Z_HARNESS_PLAN_DIR
  export Z_HARNESS_SLUG
  export Z_HARNESS_CHECKPOINT_PRODUCER="z-debug"
  export Z_HARNESS_CHECKPOINT_PHASE_ID="$seam_id"
  export Z_HARNESS_CHECKPOINT_PHASE_NAME="$phase_name"
  export Z_HARNESS_CHECKPOINT_COMPLETED_ARTIFACT="$completed_artifact"
  export Z_HARNESS_CHECKPOINT_FAST_FORWARD_GUARD="$(python3 - "$debug_md" "$completed_artifact" <<'PYEOF'
import hashlib, sys
h = hashlib.sha256()
for path in sys.argv[1:]:
    try:
        with open(path, "rb") as fh:
            h.update(path.encode("utf-8") + b"\0" + fh.read() + b"\0")
    except FileNotFoundError:
        h.update(path.encode("utf-8") + b"\0missing\0")
print(h.hexdigest())
PYEOF
)"
  export Z_HARNESS_CHECKPOINT_STALE_MODE="reject"
  export Z_HARNESS_CHECKPOINT_RESUME_COMMAND="/z-debug ${Z_HARNESS_SLUG:-<symptom>}"
  export Z_HARNESS_CHECKPOINT_NEXT_STEP="Resume /z-debug from ${debug_md}; ${next_step}"
  export Z_HARNESS_CHECKPOINT_PRODUCER_META_JSON="$(python3 - "$seam_id" "$RUN" "$debug_md" <<'PYEOF'
import json, sys
print(json.dumps({"command": "z-debug", "seam": sys.argv[1], "run": sys.argv[2], "debug_md": sys.argv[3]}))
PYEOF
)"

  COMPACTION_TRIGGERED=0
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/check-compaction.sh" || COMPACTION_TRIGGERED=$?
  if [ "$COMPACTION_TRIGGERED" -eq 1 ]; then
    CHECKPOINT_OUT="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/write-clear-checkpoint.sh")"
    printf '%s\n' "$CHECKPOINT_OUT"
    case "$CHECKPOINT_OUT" in
      STATUS:\ clear_checkpoint_fast_forward*) ;;
      STATUS:\ clear_checkpoint*) exit 0 ;;
      *) exit 1 ;;
    esac
  elif [ "$COMPACTION_TRIGGERED" -eq 2 ]; then
    # Execute Run Brief — halt finalize with reason "context pressure estimate failed in strict mode at $seam_id", then exit 1.
    exit 1
  fi
}
```

The hook owns percentage-threshold evaluation, `compaction_pause`, checkpoint metadata, resume/fast-forward state, stale-state handling, and under-threshold fallthrough. Exit `0` means continue without checkpoint side effects; exit `1` means write the shared checkpoint and stop before the next high-context phase; exit `2` is a strict-mode halt. Existing checkpoint state that matches phase/artifact/guard fast-forwards; stale state is rejected by the shared producer. Resume text always points at `$Z_HARNESS_PLAN_DIR/DEBUG.md` and the next phase, even when the completed artifact is an archive file.

Registered durable seams:

| Seam id | When it runs | Durable artifact | Next step |
|---------|--------------|------------------|-----------|
| `debug-phase2-post-evidence` | after `DEBUG.md` contains `## Evidence Inventory` with `repro_confidence` high/low, before Phase 2.5 bisect dispatch or Phase 3a | `$Z_HARNESS_PLAN_DIR/DEBUG.md` | resume at Phase 2.5 bisect gate or Phase 3a Round 1 |
| `debug-phase3a-after-round1-orchestrator` | after `archive/$RUN/round1-orchestrator.md` is written, immediately before Round 1 consultant dispatch | `$Z_HARNESS_PLAN_DIR/archive/$RUN/round1-orchestrator.md` | resume at Phase 3a Round 1 consultant dispatch using `DEBUG.md` |
| `debug-phase3a-post-hypothesis-pool` | after the initial merged `## Hypothesis Pool` is committed to `DEBUG.md`, before Phase 3b adversarial dispatch | `$Z_HARNESS_PLAN_DIR/DEBUG.md` | resume at Phase 3b adversarial dispatch |
| `debug-phase3b-post-hypothesis-pool` | after Round 2 critiques/additions are applied and the updated `## Hypothesis Pool` is committed, before Test Matrix synthesis | `$Z_HARNESS_PLAN_DIR/DEBUG.md` | resume at Phase 4 Test Matrix synthesis |
| `debug-phase5-pre-isolation` | after `## Test Matrix` and test order are written, before Phase 6 isolation starts | `$Z_HARNESS_PLAN_DIR/DEBUG.md` | resume at Phase 6 isolation cycle |
| `debug-phase6-post-scoring` | after each cycle's `## Experiment Log`, `## Score Updates`, and `## Eliminated Alternatives` changes are committed, before the next isolation/fix-gate/Round 3 transition | `$Z_HARNESS_PLAN_DIR/DEBUG.md` | resume at Phase 6 loop decision |
| `debug-phase7-pre-fix-consult` | after `## Root Cause` and Evidence coverage are written and the fix-gate preconditions hold, before `light-fix` consultant dispatch | `$Z_HARNESS_PLAN_DIR/DEBUG.md` | resume at Phase 7 fix consult |
| `debug-phase7-post-fix-plan` | after `## Fix Plan` is written, before inline implementation/Codex review | `$Z_HARNESS_PLAN_DIR/DEBUG.md` | resume at Phase 7 implementation |
| `debug-phase8-pre-postmortem` | after `## Verification` is written, before mandatory Post-mortem synthesis | `$Z_HARNESS_PLAN_DIR/DEBUG.md` | resume at Phase 9 Post-mortem |
| `debug-phase9-pre-mr-review` | after `## Post-mortem` is written, before MR-style review and action-item user gates | `$Z_HARNESS_PLAN_DIR/DEBUG.md` | resume at Phase 9 review/action-item gates |
| `debug-phase10-pre-finalize` | after post-mortem action-item disposition is recorded and before final run-brief/user-facing report generation | `$Z_HARNESS_PLAN_DIR/DEBUG.md` | resume at Phase 10 Finalize |

Skipped candidate seams: no checkpoint before `DEBUG.md` exists; no checkpoint before writing `round1-orchestrator.md` because the contamination invariant requires the orchestrator hypothesis decision to be durably written first; no checkpoint while consultants, bisect, isolation commands, Codex review, or MR review are in flight; no checkpoint between reading consultant output and committing the merged pool/scoring artifact; no checkpoint for `repro_confidence: none` before the cannot-reproduce user gate; and no checkpoint after a run-ending halt because halt finalize owns that terminal state.


## Artifact Scout preflight

Run after Setup provider logging and before the soft cost estimate, wrong-tool gate, evidence collection, bisect-isolator, doc-fetcher, or hypothesis consultant dispatch. This command has no hard pre-run cost gate, but scout output for debug/similarity is warning-only unless the classifier returns an explicit route recommendation with `route_chain_effect: "write_route_decision"`.

```bash
REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
ARTIFACT_SCOUT_INVENTORY="$Z_HARNESS_PLAN_DIR/archive/$RUN/artifact-scout-inventory.json"
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/artifact-scout-inventory.py" \
  --command /z-debug --slug "$Z_HARNESS_SLUG" --run-id "$RUN" \
  --repo-root "$REPO_ROOT" --plan-dir "$Z_HARNESS_PLAN_DIR" \
  --task "$ARGUMENTS" --output "$ARTIFACT_SCOUT_INVENTORY"
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
  description="Artifact scout for z-debug <slug>",
  prompt="current_command: /z-debug
task_or_topic: <debug symptom>
route_chain_json: <current route chain JSON>
repo_root: <abs repo root>
inventory_json_path: $Z_HARNESS_PLAN_DIR/archive/$RUN/artifact-scout-inventory.json

Inline inventory JSON:
<contents printed by scripts/artifact-scout-inventory.py>"
)
```

Write the raw response to `$Z_HARNESS_PLAN_DIR/archive/$RUN/artifact-scout.md`. Emit `artifact_scout_classified`, `artifact_scout_warning`, and `artifact_scout_route` per the contract. The warning-only debug/similar path (`STATUS: warned`, `historical_similar`, `allowed_action: warning_only`, or `route_chain_effect: "none"`) never writes `route-decision.md`, never emits `artifact_scout_route`, and never advances `route_chain`. An exact active same-slug debug run is not a similarity warning: surface the existing claim/active-run AskUser gate (continue, wait/inspect, or choose a new slug), but still write `route-decision.md` only for `ask_user` or route outcomes with `route_chain_effect: "write_route_decision"` and then emit `plan_route_decision`.

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

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the wrong-tool
     gate question via their native channel. Silent omission is forbidden. -->
`AskUserQuestion`:

**"Do you already have a concrete hypothesis for what's causing this?"**

- **"no — proceed with /z-debug"** (default) — continue to Phase 1.
- **"yes — recommend /z-fix"** — exit with one-line recommendation: "You already have a diagnosis. Run `/z-fix <symptom>` for the lightweight fix-with-known-cause flow." Do not proceed. Per the FINALIZE_STATUS rule, run **Run Brief — halt finalize** with reason `wrong tool — user has diagnosis`, then deregister before exiting (this halt occurs after a successful register).

This gate is mandatory. If the user picks "yes," exit cleanly even if `$ARGUMENTS` was non-empty.

## Phase 1 — Problem statement

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the problem
     clarification questions via their native channel. Silent omission is forbidden. -->
Ask these clarifying questions conversationally — a plain reply, **not** an `AskUserQuestion` popup (they need free-text answers anyway):

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

If `repro_confidence` is `high` or `low`, run `run_zdebug_compaction_seam "debug-phase2-post-evidence" "Phase 2 post-evidence" "$Z_HARNESS_PLAN_DIR/DEBUG.md" "continue at Phase 2.5 bisect gate or Phase 3a Round 1 using DEBUG.md Evidence Inventory"` before Phase 2.5 or Phase 3a. If `repro_confidence` is `none`, skip this seam because the cannot-reproduce user gate owns the pause.


<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the cannot-
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
     requirement and skip the bisect-isolator Agent() call. Phase 2.5 is a
     fast-path only — pipeline continues to Phase 3a if skipped. -->
Agent(
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

   Immediately after this file is written — before resolving consultant config, before dispatching any Round 1 consultant, and before any consultant output can be read — run `run_zdebug_compaction_seam "debug-phase3a-after-round1-orchestrator" "Phase 3a after orchestrator checkpoint" "$Z_HARNESS_PLAN_DIR/archive/$RUN/round1-orchestrator.md" "continue at Phase 3a Round 1 consultant dispatch using DEBUG.md Problem and Evidence Inventory"`. This preserves the contamination invariant: the orchestrator hypothesis checkpoint decision is durable before the shared hook can pause/fast-forward and before consultant output exists.


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
        requirement to the user and skip all Round 1 consultant Agent() calls.
        Phase 3a cannot complete without subagent support. -->
   Agent(
     subagent_type="agy",
     description="R1 hypothesis generation for <slug> — gemini arm",
     prompt="<AGY_PERSONA_PREFIX>MODE: generate-hypotheses-round1\n\nProblem (verbatim):\n<## Problem section>\n\nEvidence Inventory (verbatim):\n<## Evidence Inventory section>\n\nRelevant code (quoted with file:line, brief):\n<short snippets>\n\ndoc-fetcher synthesis (if relevant):\n<synthesis>\n\nAsk: independently propose 3-5 hypotheses for the root cause. Each must include a discriminating test that confirms if true AND refutes if false. Do not assume any context outside the problem statement and evidence inventory provided.\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
   )
   Agent(
     subagent_type="cursor",
     model="claude-4.6-sonnet",
     description="R1 hypothesis generation for <slug> — claude-sonnet arm",
     prompt="<CLAUDE_PERSONA_PREFIX>MODE: generate-hypotheses-round1\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
   )
   Agent(
     subagent_type="cursor",
     model="grok-4.3",
     description="R1 hypothesis generation for <slug> — grok arm",
     prompt="<GROK_PERSONA_PREFIX>MODE: generate-hypotheses-round1\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
   )
   Agent(
     subagent_type="cursor",
     model="composer-2.5",
     description="R1 hypothesis generation for <slug> — composer arm",
     prompt="<COMPOSER_PERSONA_PREFIX>MODE: generate-hypotheses-round1\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
   )
   Agent(
     subagent_type="codex-cli",
     description="R1 hypothesis generation for <slug> — codex-5.5 arm",
     prompt="<CODEX_PERSONA_PREFIX>MODE: generate-hypotheses-round1\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
   )
   ```

   **If `PERSONA_ROTATION == "false"`**, fall back to the standard 2-consultant dispatch:

   ```
   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
        requirement to the user and skip both Round 1 consultant Agent() calls.
        Phase 3a cannot complete without subagent support. -->
   Agent(
     subagent_type="consultant-secondary",
     description="R1 hypothesis generation for <slug>",
     prompt="MODE: generate-hypotheses-round1\n\nProblem (verbatim):\n<## Problem section>\n\nEvidence Inventory (verbatim):\n<## Evidence Inventory section>\n\nRelevant code (quoted with file:line, brief):\n<short snippets>\n\ndoc-fetcher synthesis (if relevant):\n<synthesis>\n\nAsk: independently propose 3-5 hypotheses for the root cause. Each must include a discriminating test that confirms if true AND refutes if false. Do not assume any context outside the problem statement and evidence inventory provided.\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
   )
   Agent(
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

After the initial `## Hypothesis Pool` is committed to `DEBUG.md`, run `run_zdebug_compaction_seam "debug-phase3a-post-hypothesis-pool" "Phase 3a post-hypothesis-pool" "$Z_HARNESS_PLAN_DIR/DEBUG.md" "continue at Phase 3b adversarial dispatch using DEBUG.md Hypothesis Pool"` before starting Phase 3b.


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
     requirement to the user and skip all Round 2 consultant Agent() calls.
     Phase 3b cannot complete without subagent support. -->
Agent(
  subagent_type="agy",
  description="R2 adversarial for <slug> — gemini arm",
  prompt="<AGY_PERSONA_PREFIX>MODE: generate-hypotheses-round2-adversarial\nschema_version: hypothesis_round2_v1\n\nProblem (verbatim):\n<## Problem>\n\nEvidence Inventory (verbatim):\n<## Evidence Inventory>\n\nHypothesis Pool (verbatim, with H<NNN> IDs):\n<## Hypothesis Pool table>\n\nAsk: given this merged hypothesis pool, return exactly TWO markdown tables in this order. Do not restate existing pool entries — your value is orthogonality and critique, not endorsement.\n\nTABLE 1 — NEW hypotheses (orthogonality hunt — failure modes absent from the pool). Columns (exact, in order):\n| claim | prediction_if_true | prediction_if_false | discriminating_test | test_cost | parallel_safe | reasoning | orthogonality_to |\n  - `test_cost` ∈ {free, cheap, medium, expensive}\n  - `parallel_safe` ∈ {true, false} — true ONLY if the discriminating test mutates no shared state\n  - `orthogonality_to` — comma-separated list of H<NNN> IDs this row fills a gap relative to (e.g. `H001, H004`)\n\nTABLE 2 — CRITIQUES of existing pool rows. Columns (exact, in order):\n| target_id | critique_type | problem | recommended_action | merge_with_id |\n  - `target_id` — H<NNN> of the row being critiqued (required; rows missing this will be dropped)\n  - `critique_type` MUST be one of: `non_discriminating_test`, `false_parallel_safe`, `duplicate`, `weak_claim`, `unclear_prediction`\n  - `problem` — concrete description; no 'looks good', no 'agree', no empty cells, no pure restatement of the target row's claim\n  - `false_parallel_safe` rows MUST cite the specific mutation in the `problem` cell (e.g. 'writes to ~/.cache/foo'), not just 'mutates state'\n  - `merge_with_id` — populated ONLY when `critique_type == duplicate` (the H<NNN> the target should merge into)\n\nTag the response with `schema_version: hypothesis_round2_v1` at the top.\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
Agent(
  subagent_type="cursor",
  model="claude-4.6-sonnet",
  description="R2 adversarial for <slug> — claude-sonnet arm",
  prompt="<CLAUDE_PERSONA_PREFIX>MODE: generate-hypotheses-round2-adversarial\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
Agent(
  subagent_type="cursor",
  model="grok-4.3",
  description="R2 adversarial for <slug> — grok arm",
  prompt="<GROK_PERSONA_PREFIX>MODE: generate-hypotheses-round2-adversarial\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
Agent(
  subagent_type="cursor",
  model="composer-2.5",
  description="R2 adversarial for <slug> — composer arm",
  prompt="<COMPOSER_PERSONA_PREFIX>MODE: generate-hypotheses-round2-adversarial\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
Agent(
  subagent_type="codex-cli",
  description="R2 adversarial for <slug> — codex-5.5 arm",
  prompt="<CODEX_PERSONA_PREFIX>MODE: generate-hypotheses-round2-adversarial\n\n<same prompt body>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
```

**If `PERSONA_ROTATION == "false"`**, fall back to the standard 2-consultant dispatch:

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip both Round 2 consultant Agent() calls.
     Phase 3b cannot complete without subagent support. -->
Agent(
  subagent_type="consultant-secondary",
  description="R2 adversarial for <slug>",
  prompt="MODE: generate-hypotheses-round2-adversarial\nschema_version: hypothesis_round2_v1\n\nProblem (verbatim):\n<## Problem>\n\nEvidence Inventory (verbatim):\n<## Evidence Inventory>\n\nHypothesis Pool (verbatim, with H<NNN> IDs):\n<## Hypothesis Pool table>\n\nAsk: given this merged hypothesis pool, return exactly TWO markdown tables in this order. Do not restate existing pool entries — your value is orthogonality and critique, not endorsement.\n\nTABLE 1 — NEW hypotheses (orthogonality hunt — failure modes absent from the pool). Columns (exact, in order):\n| claim | prediction_if_true | prediction_if_false | discriminating_test | test_cost | parallel_safe | reasoning | orthogonality_to |\n  - `test_cost` ∈ {free, cheap, medium, expensive}\n  - `parallel_safe` ∈ {true, false} — true ONLY if the discriminating test mutates no shared state\n  - `orthogonality_to` — comma-separated list of H<NNN> IDs this row fills a gap relative to (e.g. `H001, H004`)\n\nTABLE 2 — CRITIQUES of existing pool rows. Columns (exact, in order):\n| target_id | critique_type | problem | recommended_action | merge_with_id |\n  - `target_id` — H<NNN> of the row being critiqued (required; rows missing this will be dropped)\n  - `critique_type` MUST be one of: `non_discriminating_test`, `false_parallel_safe`, `duplicate`, `weak_claim`, `unclear_prediction`\n  - `problem` — concrete description; no 'looks good', no 'agree', no empty cells, no pure restatement of the target row's claim\n  - `false_parallel_safe` rows MUST cite the specific mutation in the `problem` cell (e.g. 'writes to ~/.cache/foo'), not just 'mutates state'\n  - `merge_with_id` — populated ONLY when `critique_type == duplicate` (the H<NNN> the target should merge into)\n\nTag the response with `schema_version: hypothesis_round2_v1` at the top.\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
Agent(
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

Run `run_zdebug_compaction_seam "debug-phase3b-post-hypothesis-pool" "Phase 3b post-hypothesis-pool" "$Z_HARNESS_PLAN_DIR/DEBUG.md" "continue at Phase 4 Test Matrix synthesis from DEBUG.md"` before building the Test Matrix.


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

After the Test Matrix and cycle-1 test order are committed to `DEBUG.md`, run `run_zdebug_compaction_seam "debug-phase5-pre-isolation" "Phase 5 pre-isolation" "$Z_HARNESS_PLAN_DIR/DEBUG.md" "continue at Phase 6 isolation cycle from DEBUG.md Test Matrix"` before running isolation commands.


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

After the cycle's `## Experiment Log`, `## Score Updates`, and `## Eliminated Alternatives` updates are committed to `DEBUG.md`, run `run_zdebug_compaction_seam "debug-phase6-post-scoring" "Phase 6 post-scoring" "$Z_HARNESS_PLAN_DIR/DEBUG.md" "continue at Phase 6 loop decision, then the next isolation cycle, Round 3, or Phase 7 fix-gate"` before evaluating the next high-context transition.


### Phase 6 loop logic

- **Fix-gate check:** if any active hypothesis has `posterior == very_high` AND there is a written causal mechanism (Phase 7's Root Cause draft) explaining every `EVID-NNN` in the Evidence Inventory → fix-gate open, proceed to Phase 7.
- **Otherwise:** increment cycle counter, return to Phase 6 step 1 with the remaining `active` rows in updated test order.
- **Soft warning at cycle 3** — push-notify: "z-debug cycle 3 reached without convergence. Two cycles remaining before hard halt."
<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the hard cycle
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

## Phase 7 — Root cause + fix-gate + fix

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

When the Root Cause and Evidence coverage table have been written and both fix-gate preconditions hold, run `run_zdebug_compaction_seam "debug-phase7-pre-fix-consult" "Phase 7 pre-fix-consult" "$Z_HARNESS_PLAN_DIR/DEBUG.md" "continue at Phase 7 light-fix consultant dispatch from DEBUG.md Root Cause"` before capturing `PRE_FIX_SHA` and dispatching fix consultants.


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
        requirement and skip all fix consult Agent() calls. Phase 7 fix gate
        cannot complete without subagent support. -->
   Agent(subagent_type="agy", description="Fix consult for <slug> — gemini arm",
         prompt="MODE: light-fix\n\n<sections per Phase-visibility matrix row 7>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]")
   Agent(subagent_type="cursor", model="claude-4.6-sonnet", description="Fix consult for <slug> — claude-sonnet arm",
         prompt="MODE: light-fix\n\n<same sections>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]")
   Agent(subagent_type="cursor", model="grok-4.3", description="Fix consult for <slug> — grok arm",
         prompt="MODE: light-fix\n\n<same sections>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]")
   Agent(subagent_type="cursor", model="composer-2.5", description="Fix consult for <slug> — composer arm",
         prompt="MODE: light-fix\n\n<same sections>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]")
   Agent(subagent_type="codex-cli", description="Fix consult for <slug> — codex-5.5 arm",
         prompt="MODE: light-fix\n\n<same sections>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]")
   ```

   **If `PERSONA_ROTATION == "false"`**, fall back to the standard 2-consultant dispatch:

   ```
   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
        requirement and skip both fix consult Agent() calls. Phase 7 fix gate
        cannot complete without subagent support. -->
   Agent(subagent_type="consultant-secondary", description="Fix consult for <slug>",
         prompt="MODE: light-fix\n\n<sections per Phase-visibility matrix row 7>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]")
   Agent(subagent_type="consultant-primary", description="Fix consult for <slug>",
         prompt="MODE: light-fix\n\n<same sections>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]")
   ```
3. **Synthesize + push back.** One reason it might be wrong per recommendation. Flag shortcuts.
<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the fix approval
     question via their native channel. Silent omission is forbidden. -->
4. **Present + approve.** Present the synthesized fix as a conversational brief — the approach, the one reason each recommendation might be wrong (from step 3), and any flagged shortcuts with their tradeoff — then give your recommendation and invite the user to reply (approve as proposed / modify <X> / abandon). Do **not** use an `AskUserQuestion` popup; this is a design decision the user should be able to interrogate.
5. **Write `## Fix Plan`** section to DEBUG.md:

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

After `## Fix Plan` is committed to `DEBUG.md`, run `run_zdebug_compaction_seam "debug-phase7-post-fix-plan" "Phase 7 post-fix-plan" "$Z_HARNESS_PLAN_DIR/DEBUG.md" "continue at Phase 7 inline implementation from DEBUG.md Fix Plan"` before inline implementation and Codex review.


6. **Inline implementation.** Implementer self-check: no broad exception handlers, no scope expansion, no unsolicited validation, no new public surface, no stale comments.

   #### Git history-rewrite safety

   Before recommending any `git reset --hard HEAD~N`, `git commit --amend`, or interactive-rebase squash on a branch tracking an upstream: for each commit being rewritten, run `git branch -r --contains <sha>`. If the upstream ref appears, STOP — recommend rebase or new-commit instead, never silent rewrite. Force-push to main requires explicit per-incident user authorization with (i) list of overwritten commits and (ii) content-equivalence/superset demonstration.

7. **Codex review** (non-negotiable). Retry-once policy. Track `REVIEW_CYCLES`.

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

After `## Verification` is committed to `DEBUG.md`, run `run_zdebug_compaction_seam "debug-phase8-pre-postmortem" "Phase 8 pre-postmortem" "$Z_HARNESS_PLAN_DIR/DEBUG.md" "continue at Phase 9 Post-mortem synthesis from DEBUG.md Verification"` before writing the Post-mortem.


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

After `## Post-mortem` is committed to `DEBUG.md`, run `run_zdebug_compaction_seam "debug-phase9-pre-mr-review" "Phase 9 pre-MR-review" "$Z_HARNESS_PLAN_DIR/DEBUG.md" "continue at Phase 9 MR-style review and action-item gates from DEBUG.md Post-mortem"` before the MR-review gate and action-item conversion prompts.


<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the MR-review
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

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the post-mortem
     action-item disposition question via their native channel. Silent omission
     is forbidden. -->
After writing, ask the user via `AskUserQuestion`:
- "Convert action items into follow-up tasks?" → If yes, the orchestrator appends them to a designated `TASKS.md` (user picks which slug, or creates a fresh `audit-<topic>` slug) and the user can later `/z-execute` them.
- "Convert regression-test action items into a /z-test follow-up" → For each action item shaped like `Add regression test ...`, record the invariant + failure-class + target-file hint into `$Z_HARNESS_PLAN_DIR/test-followups.md` (a flat list of seed entries shaped like Phase 2 drafts in `/z-test`). On the next `/z-plan` + `/z-test` cycle (or if the user re-runs `/z-test` on this same slug after seeding follow-up production tasks), these become mandatory TESTS.md entries. Closes the post-mortem loop automatically — the next plan run cannot ship without the regression test the post-mortem flagged.
- "Just record and move on" → leave the Post-mortem section as a standalone record.

Push-notify: "Post-mortem ready: `$Z_HARNESS_PLAN_DIR/DEBUG.md` Post-mortem section. Action items: <N> (converted to tasks: <yes/no>)."

After action-item disposition is recorded, run `run_zdebug_compaction_seam "debug-phase10-pre-finalize" "Phase 10 pre-finalize" "$Z_HARNESS_PLAN_DIR/DEBUG.md" "continue at Phase 10 Finalize and final user-facing report from DEBUG.md"` before Run Brief finalize and the final user-facing report.


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

<!-- include: _fragments/run-brief-finalize.md -->

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

<!-- include: _fragments/run-brief-finalize.md -->

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

<!-- include: _fragments/run-brief-finalize.md -->

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
| `subagent` | yes | Phase 2.5 bisect-isolator Agent(); Phase 3a Round 1 Agent() calls (2-consultant fallback when `experiment.persona_rotation=false`, or fixed 5-panel when `experiment.persona_rotation=true`: agy, cursor@claude-4.6-sonnet, cursor@grok-4.3, cursor@composer-2.5, codex-cli); Phase 3b Round 2 Agent() calls (same panel structure as Phase 3a); Phase 7 fix consult Agent() calls (same panel structure) |
| `ask_user` | yes | Empty arguments gate; Setup slug confirmation; Phase 0 wrong-tool gate; Phase 1 problem clarification; Phase 2 cannot-reproduce gate; Phase 6 hard cycle cap gate; Phase 7 fix approval; Phase 9 MR-review gate; Phase 9 action-item disposition |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
