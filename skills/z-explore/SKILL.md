---
name: z-explore
disable-model-invocation: false
description: depth-scaled codebase terrain explorer; quick scout through deep MAP.md terrain synthesis
argument-hint: "<question> [--depth=quick|standard|deep] [--repo] [--slug=<kebab>] [--surface=auto|off|force]"
runtime: c1
driver_features_required:
  - subagent
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are running the **z-harness `/z-explore`** pipeline — a depth-scaled terrain discovery command from quick scouts through deep MAP.md synthesis.

Question (from `$ARGUMENTS`):

$ARGUMENTS

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the question
     "What question should I explore?" to the user via their native channel and
     accept a text reply. Silent omission is forbidden. -->
**If the question above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask "What question should I explore?". Wait for their reply. Treat their reply as the question and continue. Do not proceed past this point without a concrete question.

Strict, multi-phase. Do not skip phases. `/z-explore` produces a terrain note only — it maps terrain, it does not pick an approach. Implementation and approach-selection happen later via `/z-brainstorm` or `/z-plan`.

**Depth modes** (parsed from `--depth=` argument):
- `quick` (default): 1-2 Haiku Explores, inline findings. Low cost, fast turnaround.
- `standard`: up to 3 Haiku Explores, persisted EXPLORE.md + surface-map.json. Moderate cost.
- `deep`: up to 3 Haiku/Sonnet Explores, full research-draft + bundled cross-LLM critique + MAP.md. Full terrain synthesis.

**Known v1 limitation:** `Agent()` does not expose a per-call wall-clock timeout. Subagents that hang block the run. User escape: ctrl-c.

## Setup

1. **Parse `--depth=` flag** from `$ARGUMENTS`. If present, strip it and set `EXPLORE_DEPTH=<quick|standard|deep>`. Default: `quick`. Valid values only — if unrecognized, error and ask user. Initialize `CITATION_COUNT=0` and `GAP_COUNT=0` for telemetry tracking during synthesis (see Phase 4).

2. **Parse `--slug=<value>`, `--resume-phase=<seam_id>`, and `--resume-run=<run-id>` flags** from `$ARGUMENTS` before slug derivation. Strip each entire token from the cleaned exploration question. The stripped resume tokens MUST NOT appear in prompts, slug derivation, or `input_hash`; store them as `RESUME_PHASE` and `RESUME_RUN` for the deep-mode resume gate. If `--slug=` is present, the explicit slug overrides auto-derivation.

   **Derive a research slug** (only if `--slug=` was not provided): from the cleaned question, short kebab-case, 2-4 words (e.g. "how does the retry logic work?" → `retry-logic`). Run `bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" all_plan_slugs` to check for existing slug names. Slug-collision handling is deferred to **Phase 1** (after the cost gate, for deep mode) or handled inline for quick/standard.

   If `--slug=` was explicitly provided, skip auto-derivation.

3. **Export** `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")` for all subsequent shell calls and subagents.

4. Pick a run id: `RUN="${RESUME_RUN:-$(date -u +%Y%m%dT%H%M%SZ)-<slug>}"` so checkpoint resumes validate the original archive path instead of a fresh run directory.

5. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`

6. Capture the z-harness plugin version stamp and log the explore run start (merge version blob into the payload):
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["question"] = sys.argv[2]; v["depth"] = sys.argv[3]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>" "$EXPLORE_DEPTH")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" explore_run_start "$START_PAYLOAD"
   ```

7. **Parent attribution (sub-command contract).** If `$Z_HARNESS_PARENT_RUN_ID` is set in the environment (i.e. this sub-command is being dispatched by a meta-orchestrator like `/z-research`), include `parent_run_id` and `parent_command` fields in every subsequent `log-event.sh` payload. Example:

   ```bash
   bash log-event.sh "$RUN" some_event "$(python3 -c 'import json,os,sys; p=json.loads(sys.argv[1]);
   pid=os.environ.get("Z_HARNESS_PARENT_RUN_ID"); pcmd=os.environ.get("Z_HARNESS_PARENT_COMMAND");
   if pid: p["parent_run_id"]=pid;
   if pcmd: p["parent_command"]=pcmd;
   print(json.dumps(p))' "$ORIG_PAYLOAD")"
   ```

   If env vars absent → emit events as today (no attribution fields). Backward compatible.

8. Notification policy: see [docs/human/config.md](docs/human/config.md) (notify.level key).

9. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 2 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.

**Setup does NOT mutate `$Z_HARNESS_PLAN_DIR/MAP.md` or any sibling artifact.**

**All paths in subsequent phases live under `$Z_HARNESS_PLAN_DIR/`:**
- `$Z_HARNESS_PLAN_DIR/MAP.md`
- `$Z_HARNESS_PLAN_DIR/EXPLORE.md`
- `$Z_HARNESS_PLAN_DIR/surface-map.json`
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/...`

## Shared context checkpoint hook/check contract for deep terrain mode

`/z-explore --depth=deep` owns the active terrain checkpoint seams inherited by the legacy `/z-map` wrapper. It MUST NOT keep workflow-local acknowledgement files or direct `handoff.json` writers. Do not write `handoff.json` directly; call `scripts/check-compaction.sh` first and call `scripts/write-clear-checkpoint.sh` only when the shared check exits `1`.

Standard seam call pattern:

```bash
run_workflow_compaction_seam() {
  local seam_id="$1" phase_name="$2" completed_artifact="$3" next_step="$4"
  shift 4 || true
  export Z_HARNESS_PLAN_DIR
  export Z_HARNESS_SLUG
  export Z_HARNESS_CHECKPOINT_STATUS="context_pressure"
  export Z_HARNESS_CHECKPOINT_PRODUCER="${Z_HARNESS_CHECKPOINT_PRODUCER:-z-explore}"
  export Z_HARNESS_CHECKPOINT_PHASE_ID="$seam_id"
  export Z_HARNESS_CHECKPOINT_PHASE_NAME="$phase_name"
  export Z_HARNESS_CHECKPOINT_COMPLETED_ARTIFACT="$completed_artifact"
  export Z_HARNESS_CHECKPOINT_FAST_FORWARD_GUARD="$(python3 - "$Z_HARNESS_PLAN_DIR/MAP.md" "$completed_artifact" "$@" <<'PYEOF'
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
  export Z_HARNESS_CHECKPOINT_RESUME_COMMAND="/z-explore --depth=deep ${Z_HARNESS_SLUG:-<topic>} --resume-phase=$seam_id --resume-run=$RUN"
  export Z_HARNESS_CHECKPOINT_NEXT_STEP="Resume /z-explore --depth=deep from $Z_HARNESS_PLAN_DIR; ${next_step}"
  export Z_HARNESS_CHECKPOINT_PRODUCER_META_JSON="$(python3 - "$seam_id" "$RUN" "$completed_artifact" <<'PYEOF'
import json, sys
print(json.dumps({"command": "z-explore", "compatibility_alias": "z-map", "seam": sys.argv[1], "run": sys.argv[2], "completed_artifact": sys.argv[3]}))
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
    # Execute halt finalize with reason "context pressure estimate failed in strict mode at $seam_id", then exit 1.
    exit 1
  fi
}
```

Registered deep terrain seams:

| Seam id | When it runs | Durable artifact | Next step |
|---------|--------------|------------------|-----------|
| `map-phase4-pre-critique` | after `research-draft.md` is written, before bundled consultant critique dispatch | `$Z_HARNESS_PLAN_DIR/archive/$RUN/research-draft.md` | resume at critique dispatch |
| `map-phase4-post-critique` | after critique transcripts are archived and `critique-manifest.json` is written, before revised-draft synthesis | `$Z_HARNESS_PLAN_DIR/archive/$RUN/critique-manifest.json` | resume at synthesis/revision |
| `map-phase4-pre-map-write` | after the revised draft is durable, before final `MAP.md` synthesis/write | `$Z_HARNESS_PLAN_DIR/archive/$RUN/research-draft.md` | resume at MAP.md synthesis |
| `map-phase5-pre-final-review` | after `MAP.md` is written and promotion/citation metadata is durable, before final review/finalize checks | `$Z_HARNESS_PLAN_DIR/MAP.md` | resume at final review |
| `map-phase5-pre-user-report` | after final review accepts `MAP.md`, before user-facing report generation | `$Z_HARNESS_PLAN_DIR/MAP.md` | resume at final user-facing report |

Skipped candidate seams: no check before a deep-mode durable artifact exists; no check while Explore or consultant workers are in flight; no check after terminal halt because halt finalize owns that state.

The shared hook emits `compaction_pause` through `check-compaction.sh` only when the configured percentage threshold is crossed; under-threshold fallthrough continues without checkpoint side effects, and stale-state handling is delegated to `write-clear-checkpoint.sh`.

### Deep-mode resume-phase gate

If `$ARGUMENTS` includes `--resume-phase=<seam_id>`, strip that flag from the cleaned exploration question before slug/input-hash derivation. Validate the corresponding `$Z_HARNESS_PLAN_DIR/.clear-checkpoint-<seam_id>.json` before route/cost/doc/explore dispatch, recompute the fast-forward guard from the current durable artifacts, and then jump directly to the recorded next phase. Never rerun earlier Explore or consultant work silently on a checkpoint resume.

```bash
RESUME_PHASE="$(printf '%s\n' "$ARGUMENTS" | python3 -c 'import re,sys; text=sys.stdin.read(); m=re.search(r"--resume-phase=([^\\s]+)", text); print(m.group(1) if m else "")')"
RESUME_RUN="$(printf '%s\n' "$ARGUMENTS" | python3 -c 'import re,sys; text=sys.stdin.read(); m=re.search(r"--resume-run=([^\\s]+)", text); print(m.group(1) if m else "")')"
if [ -n "$RESUME_RUN" ]; then RUN="$RESUME_RUN"; fi
if [ -n "$RESUME_PHASE" ]; then
  case "$RESUME_PHASE" in
    map-phase4-pre-critique) RESUME_TARGET="critique"; REQUIRED_ARTIFACT="$Z_HARNESS_PLAN_DIR/archive/$RUN/research-draft.md" ;;
    map-phase4-post-critique) RESUME_TARGET="revision"; REQUIRED_ARTIFACT="$Z_HARNESS_PLAN_DIR/archive/$RUN/critique-manifest.json" ;;
    map-phase4-pre-map-write) RESUME_TARGET="map-write"; REQUIRED_ARTIFACT="$Z_HARNESS_PLAN_DIR/archive/$RUN/research-draft.md" ;;
    map-phase5-pre-final-review) RESUME_TARGET="final-review"; REQUIRED_ARTIFACT="$Z_HARNESS_PLAN_DIR/MAP.md" ;;
    map-phase5-pre-user-report) RESUME_TARGET="user-report"; REQUIRED_ARTIFACT="$Z_HARNESS_PLAN_DIR/MAP.md" ;;
    *) echo "Unknown /z-explore resume phase: $RESUME_PHASE" >&2; exit 1 ;;
  esac
  STATE_FILE="$Z_HARNESS_PLAN_DIR/.clear-checkpoint-${RESUME_PHASE}.json"
  CURRENT_GUARD="$(python3 - "$Z_HARNESS_PLAN_DIR/MAP.md" "$REQUIRED_ARTIFACT" <<'PYEOF'
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
  python3 - "$STATE_FILE" "$RESUME_PHASE" "$REQUIRED_ARTIFACT" "$CURRENT_GUARD" <<'PYEOF' || exit 1
import json, sys
from pathlib import Path
state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if state.get("phase_id") != sys.argv[2] or state.get("completed_artifact") != sys.argv[3]:
    raise SystemExit("stale /z-explore checkpoint state")
if state.get("fast_forward_guard") != sys.argv[4]:
    raise SystemExit("stale /z-explore checkpoint guard")
PYEOF
  export Z_EXPLORE_RESUME_TARGET="$RESUME_TARGET"
  # Continue by entering the phase/step named by Z_EXPLORE_RESUME_TARGET; do not rerun route/cost/doc/explore/critique phases before that target.
fi
```

Resume target dispatch is mandatory: `critique` starts at Phase 4 deep-mode step 2, `revision` starts at Phase 4 deep-mode step 3, `map-write` starts at Phase 4 deep-mode step 4, `final-review` starts at Phase 5 validation/review, and `user-report` starts at Phase 5 push-notify/final message. Do not run Route Check, Phase 1, Phase 2, or Phase 3 when `Z_EXPLORE_RESUME_TARGET` is set.

<!-- ROUTE_CHECK_START -->
## Route check

If `Z_EXPLORE_RESUME_TARGET` is set, skip Route Check entirely and enter the target phase/step declared by the resume gate.

Advisory-only routing. Run this route check before Phase 1. Use only already-known signals from the question, slug/artifact collision check, and docs availability.

Never auto-dispatch. Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md` and present the user with recommended next steps via `AskUserQuestion`:

- `/z-explore --depth=deep` — full MAP.md with cross-LLM critique when deep terrain certainty is required.
- `/z-explain` — targeted explanation of a specific code path the explore uncovered.
- `/z-learn` — progressive codebase tutoring when the user wants orientation.
- `/z-report` — structured report on specific findings.
- `/z-plan` — turn clear terrain into a plan.

Present these as advisory options and let the user choose. Never dispatch automatically.

If the user chooses to stay in `/z-explore`, log the route check and continue.
<!-- ROUTE_CHECK_END -->

## Phase telemetry (mandatory)

At the **start** of each phase, record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
# ... AskUserQuestion ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
```

---

## Phase 1 — Cost gate

If `Z_EXPLORE_RESUME_TARGET` is set, skip Phase 1.

Depth-dependent cost handling:

**`quick` mode:** No cost gate. Proceed directly to Phase 2.

**`standard` mode:** Simple cost note — log a `cost_note` event stating estimated ~500k tokens, then proceed without user prompt.

**`deep` mode:** Full cost gate for deep terrain synthesis. Present the cost up front via `AskUserQuestion` with three options:

<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the cost-gate
     question (Proceed/Reduce/Abandon) via their native channel and accept a
     reply before any subagent dispatch. Silent omission is forbidden. -->
- **Proceed (~2M tokens)** — full fan-out, up to 3 parallel Explores + cross-LLM critique.
- **Reduce to 1 Explore** — single Explore, lighter spend (~700k-1M tokens).
- **Abandon** — exit cleanly, write nothing.

Log the user's pick:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cost_gate_decision \
  "$(printf '{"choice":"%s"}' "<proceed|reduce|abandon>")"
```

If `abandon`: exit. If `reduce`: set `EXPLORE_BUDGET=1`. Otherwise `EXPLORE_BUDGET=3`.

For **deep** mode: after the cost gate, run Phase 0.5 slug + artifact collision handling (check existing `$Z_HARNESS_PLAN_DIR/` dirs and `MAP.md`, prompt user for archive-and-start-fresh / continue / abort).

Checkpoint: `phase1-cost-gate.md`.

## Phase 2 — Doc grounding

If `Z_EXPLORE_RESUME_TARGET` is set, skip Phase 2.

If Setup step 9 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip the Agent() call. The doc-fetcher phase
     will be skipped and Phase 3 Explores will proceed without doc grounding. -->
```
Agent(
  subagent_type="doc-fetcher",
  description="Doc context for <slug>",
  prompt="query: <one-sentence summary of the question>\nrepo_root: <abs path>\ndepth: standard"
)
```

It returns a tight synthesis: matched concepts, key files with line ranges, invariants. If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed without doc grounding. If `STATUS: partial`, note the gap for Phase 3.

If a `DRIFT WARNING` block appears in the return, log a `doc_drift` event per affected slug:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
  '{"concept":"<slug>","claim":"<what doc said>","reality":"<what code says>","file":"<path>"}'
```

**No Explore here.** Phase 2 is doc-fetcher only. Explore happens in Phase 3.

For `quick` mode, if doc-fetcher returns synthesis, use it directly to inform the inline output — do not dispatch additional Explores unless synthesis is empty or `STATUS: partial`.

Checkpoint: `phase2-doc-grounding.md`.

## Phase 3 — Surface discovery

If `Z_EXPLORE_RESUME_TARGET` is set, skip Phase 3.

Dispatch `Explore` subagents based on `EXPLORE_DEPTH`:

### quick mode (1-2 Haiku Explores)

Dispatch 1-2 `Explore` agents (Haiku) covering the most important facets of the question. Send all calls in **one message** so they run in parallel:

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip the Agent() calls. -->
```
Agent(
  subagent_type="Explore",
  model="haiku",
  description="Facet A: <short label>",
  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
)
Agent(
  subagent_type="Explore",
  model="haiku",
  description="Facet B: <short label>",
  prompt="<TARGETED sub-question>\n\n..."
)
```

Track `EXPLORES_DISPATCHED` and `EXPLORES_SUCCEEDED` per exploration telemetry conventions.

### standard mode (up to 3 Haiku Explores)

Dispatch up to 3 parallel `Explore` agents (Haiku) on **distinct facets**:

```
Agent(
  subagent_type="Explore",
  model="haiku",
  description="Facet A: <short label>",
  prompt="<TARGETED sub-question>..."
)
Agent(
  subagent_type="Explore",
  model="haiku",
  description="Facet B: <short label>",
  prompt="..."
)
Agent(
  subagent_type="Explore",
  model="haiku",
  description="Facet C: <short label>",
  prompt="..."
)
```

### deep mode (up to 3 Haiku/Sonnet Explores)

For deep terrain synthesis, dispatch up to `EXPLORE_BUDGET` (3 or 1) parallel `Explore` subagents. Use Haiku for locating tasks, Sonnet for interpretation tasks:

```
Agent(
  subagent_type="Explore",
  model="haiku",
  description="Facet A: <short label>",
  prompt="<TARGETED sub-question>..."
)
```

**When to upgrade Explore to Sonnet:** if the facet requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Haiku. Interpreting > Sonnet.

**Track three counts separately:**
- `EXPLORE_BUDGET` — the planned cap (1 or 3 for deep; 1-2 for quick; 2-3 for standard).
- `EXPLORES_DISPATCHED` — the number of `Explore` `Agent()` calls actually sent.
- `EXPLORES_SUCCEEDED` — the number of calls that returned a usable result.

For every Explore that fails or returns malformed output, log it and surface the failure:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" explore_failure \
  "$(printf '{"facet":"%s","reason":"%s"}' "<facet-label>" "<short reason>")"
```

The final frontmatter uses `EXPLORES_SUCCEEDED` for `explore_calls:`. If `EXPLORES_DISPATCHED - EXPLORES_SUCCEEDED > 0`, emit an additional `explore_failures: <N>` field.

Checkpoint: `phase3-explores.md` (synthesis of all Explore returns).

## Phase 4 — Synthesis

If `Z_EXPLORE_RESUME_TARGET` is `critique`, `revision`, or `map-write`, enter the matching deep-mode numbered step below and do not execute earlier Phase 4 deep-mode steps.

Write findings with citation enforcement, adapted per depth:

### quick mode — inline output

Write findings inline as part of the final response. Sections in this exact order:

```markdown
## Findings
- <claim> (path/to/file.rs:42)
- <claim> (path/to/other.py:117-130)

## Gaps
- <anything the Explores could not resolve>

## Start here
- <the single file:line the orchestrator should open first, and why>

## Next
- Recommended next steps using other /z-* commands (advisory only)
```

**Citation requirement.** Every finding MUST cite a `file:line` (or `file:line-line` range) using the broadened regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`, plus extensionless allowlist `Makefile`, `Dockerfile`. Markdown link form `[label](path:line)` is allowed.

**Demotion rule.** Findings without a `file:line` citation are demoted to **Gaps** — do not silently drop them, and do not add a fake citation.

**No-recommendation section (deep and standard modes only).** For quick mode, explicitly state at the end: *This is a terrain scout only. No approach recommendations are implied.*

### standard mode — persist EXPLORE.md + surface-map.json

Write `$Z_HARNESS_PLAN_DIR/EXPLORE.md` with:

```markdown
---
artifact: explore
slug: <slug>
generated_at: <ISO-8601 UTC>
command: /z-explore "<question>" --depth=standard [--slug=<value>]
input_hash: <computed in Phase 5>
depends_on: []
explore_calls: <EXPLORES_SUCCEEDED>
---

# Explore: <question>

## Findings
<bulleted list with file:line citations>

## Gaps
<bulleted list>

## Start here
<file:line recommendation>

## No-recommendation
This exploration explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.

## Next
- /z-explore <topic> --depth=deep — full MAP.md with cross-LLM critique
- /z-explain <topic> — targeted explanation
- /z-learn <topic> — progressive codebase tutoring
```

Also write `$Z_HARNESS_PLAN_DIR/surface-map.json`:

```json
{
  "slug": "<slug>",
  "generated_at": "<ISO-8601 UTC>",
  "findings": [{"claim": "...", "files": ["path:line"]}],
  "gaps": ["..."],
  "start_here": {"file": "path", "line": N, "reason": "..."},
  "explore_calls": <N>
}
```

### deep mode — full research pipeline

1. **Write research-draft.md** — draft cited terrain findings for deep synthesis:
   ```markdown
   ## Findings
   ## Constraints discovered
   ## Open questions
   ## No-recommendation
   ```
   With citation enforcement, demotion rule, and the invariant `## No-recommendation` section.

   After `research-draft.md` is durable, checkpoint before bundled consultant critique:
   ```bash
   run_workflow_compaction_seam \
     "map-phase4-pre-critique" \
     "Phase 4 research draft before critique" \
     "$Z_HARNESS_PLAN_DIR/archive/$RUN/research-draft.md" \
     "continue at bundled consultant critique dispatch"
   ```

2. **Bundled consultant critique** — review the draft for terrain gaps/errors. Spawn **both** consultants in parallel:
   ```
   Agent(
     subagent_type="consultant-primary",
     description="Research review (Gemini) for <slug>",
     prompt="MODE: research-review\n\nOriginal question: <question>\n\nResearch draft:\n<paste research-draft.md verbatim>\n\nReturn three sections only: Gaps, Errors, Missing constraints. Do NOT recommend an approach."
   )
   Agent(
     subagent_type="consultant-secondary",
     description="Research review (Codex) for <slug>",
     prompt="MODE: research-review\n\n..."
   )
   ```
   Per-consultant failure policy: retry once, then log failed. Require at least one successful critique before revising; if both fail, use the both-consultants-failed `ask_user` gate before proceeding.

   After critique transcripts are archived, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/critique-manifest.json`, then checkpoint before revised-draft synthesis:
   ```bash
   run_workflow_compaction_seam \
     "map-phase4-post-critique" \
     "Phase 4 critiques archived before revision" \
     "$Z_HARNESS_PLAN_DIR/archive/$RUN/critique-manifest.json" \
     "continue at research-draft revision"
   ```

3. **Revise** — update research-draft.md with critique, add `## Cross-LLM review notes` section.

   After the revised draft is durable, checkpoint before final MAP.md synthesis/write:
   ```bash
   run_workflow_compaction_seam \
     "map-phase4-pre-map-write" \
     "Phase 4 revised draft before MAP.md write" \
     "$Z_HARNESS_PLAN_DIR/archive/$RUN/research-draft.md" \
     "continue at MAP.md synthesis and atomic write"
   ```

4. **Write MAP.md** — final deep-mode terrain output format:
   ```markdown
   ---
   artifact: map
   slug: <slug>
   generated_at: <ISO-8601 UTC>
   command: /z-explore "<question>" --depth=deep [--slug=<value>]
   input_hash: <16 hex chars>
   depends_on: []
   explore_calls: <EXPLORES_SUCCEEDED>
   status: <complete | complete_no_critique>
   ---
   ```

   After `MAP.md` is atomically written, checkpoint before final review/finalize checks:
   ```bash
   run_workflow_compaction_seam \
     "map-phase5-pre-final-review" \
     "Phase 5 MAP.md written before final review" \
     "$Z_HARNESS_PLAN_DIR/MAP.md" \
     "continue at MAP.md final review and citation checks"
   ```

Checkpoint: `phase4-synthesis.md` (or `phase4-draft.md` → `phase4-critiques.md` → `phase4-revised.md` for deep mode).

## Phase 5 — Finalize

If `Z_EXPLORE_RESUME_TARGET` is `final-review`, start at validation/review. If it is `user-report`, skip validation/review and start at push-notify/final message.

Compute `input_hash` per the SPEC algorithm:

```
input_hash = sha256(canonicalize(
    question + "\n---\n" +
    doc_fetcher_synthesis_or_empty + "\n---\n" +
    explore_synthesis_or_empty + "\n---\n" +
    research_md_or_empty
)).hexdigest()[:16]
```

`canonicalize`: strip leading/trailing whitespace; collapse all internal runs of whitespace to single space.

Write the final output artifact based on depth:

- **quick**: inline findings in the response (no persistent file artifact beyond archive).
- **standard**: update `EXPLORE.md` frontmatter with `input_hash:` and `surface-map.json` with `input_hash`.
- **deep**: write `$Z_HARNESS_PLAN_DIR/MAP.md` with complete frontmatter.

- **Citation enforcement:** Findings without a `file:line` match are demoted to `## Gaps` by the synthesis phase. Count demoted findings as `GAP_COUNT` and cited findings as `CITATION_COUNT` for telemetry. Both counts are included in the `explore_run_end` payload.

Log run end with telemetry, including citation and gap counts (tracked during Phase 4 synthesis):

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" explore_run_end \
  "$(printf '{"slug":"%s","depth":"%s","explores_dispatched":%d,"explores_succeeded":%d,"explore_calls":%d,"explore_failures":%d,"citation_count":%d,"gap_count":%d,"map_written":%s,"critique_status":"%s","status":"%s"}' \
     "$Z_HARNESS_SLUG" "$EXPLORE_DEPTH" "${EXPLORES_DISPATCHED:-0}" "${EXPLORES_SUCCEEDED:-0}" "${EXPLORES_SUCCEEDED:-0}" "$(( ${EXPLORES_DISPATCHED:-0} - ${EXPLORES_SUCCEEDED:-0} ))" "${CITATION_COUNT:-0}" "${GAP_COUNT:-0}" "${MAP_WRITTEN:-false}" "${CRITIQUE_STATUS:-none}" "<complete|complete_no_critique|scout>")"
```

After final review accepts `MAP.md` and `explore_run_end` telemetry is durable, checkpoint before user-facing report generation:
```bash
run_workflow_compaction_seam \
  "map-phase5-pre-user-report" \
  "Phase 5 MAP.md accepted before user report" \
  "$Z_HARNESS_PLAN_DIR/MAP.md" \
  "continue at final user-facing report"
```

Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:

```
Explore complete. Depth: <depth>.

Recommended next step:
  /z-explore <topic> --depth=deep — full MAP.md with cross-LLM critique
  /z-explain <topic> — targeted explanation of a specific code path
  /z-learn <topic>  — progressive codebase tutoring
  /z-plan <task>    — go straight to planning if terrain is clear enough
```

---

## Operating principles

- **Terrain mapping, not direction picking.** The `## No-recommendation` section is invariant for deep and standard modes. Quick mode explicitly states the scout nature.
- **Citations are non-negotiable.** No `file:line` → not a finding.
- **Depth discipline.** Respect the selected depth. Quick means fast and lightweight; deep means thorough with critique.
- **Cost discipline.** Quick mode skips the cost gate entirely. Deep mode has the full gate. Exceeding 2M tokens logs a `cost_warning`.
- **Log everything.** Every Explore dispatch, consultant call, demotion — via `scripts/log-event.sh`.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | All `Agent(...)` calls (doc-fetcher Phase 2, Explore Phase 3, consultant-primary + consultant-secondary Phase 4 deep) |
| `ask_user` | yes | Empty-question gate, route check, cost gate Phase 1 (deep), slug-collision + MAP.md collision Phase 1 (deep), both-consultants-failed (deep) |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent omission is forbidden. Each gated call site is annotated with a `<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
