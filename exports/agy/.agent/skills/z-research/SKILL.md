---
name: z-research
description: "Higher-order meta-orchestrator. Composes /z-map (terrain) and /z-brainstorm (framings), then runs adversarial synthesis panel (3 perspectives + judge) producing RESEARCH.md with 10-section schema including approach decision matrix. Cost 3–6M token..."
---

You are running the **z-harness `/z-research`** meta-orchestrator pipeline.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

Strict, multi-phase. Do not skip phases. `/z-research` orchestrates sub-commands and an adversarial synthesis panel — it does **not** write MAP.md or BRAINSTORM.md content directly. Those artifacts are exclusively owned by `/z-map` and `/z-brainstorm` respectively.

**Cost warning:** this pipeline runs up to 3M tokens for sub-commands + 3M tokens for the synthesis panel (3 perspectives @ ~1M each) + 0.5M for the judge. Total: 3–6M tokens. The cost gate in Phase 0.5 always runs before dispatch.

---

## Argument parsing

Parse `$ARGUMENTS` before doing anything else:

```bash
TOPIC=""
SLUG_OVERRIDE=""
_args=($ARGUMENTS)
_i=0
while [ $_i -lt ${#_args[@]} ]; do
  _arg="${_args[$_i]}"
  case "$_arg" in
    --slug=*) SLUG_OVERRIDE="${_arg#--slug=}" ;;
    *)        TOPIC="$TOPIC $_arg" ;;
  esac
  _i=$((_i+1))
done
TOPIC="$(echo "$TOPIC" | xargs)"  # trim leading/trailing whitespace
```

---

## Setup

### Step 1 — Topic gate

If `$TOPIC` is empty or whitespace, do NOT auto-invent a topic. Use `AskUserQuestion` to ask: "What research topic should I synthesize? (question or technical area)" Wait for the reply. Treat the reply as `$TOPIC` and continue.

### Step 2 — Derive slug

If `--slug=` was provided, use `$SLUG_OVERRIDE` as the slug. Otherwise derive a short kebab-case slug (2–4 words) from `$TOPIC`. The stripped `--slug=` token MUST NOT appear in any prompt to subagents and MUST NOT be included in the canonical text fed into `input_hash`.

```bash
SLUG="<derived-or-overridden-kebab-slug>"
export Z_HARNESS_SLUG="$SLUG"
```

### Step 3 — Resolve plan dir and RUN id

```bash
Z_HARNESS_PLAN_DIR="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")"
export Z_HARNESS_PLAN_DIR
RUN="$(date -u +%Y%m%dT%H%M%SZ)-$SLUG"
mkdir -p "$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts"
mkdir -p "$Z_HARNESS_PLAN_DIR/archive/$RUN/panel"
mkdir -p "$Z_HARNESS_PLAN_DIR/archive/$RUN/subruns"
export RUN
```

### Step 4 — Log run start + providers

```bash
VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
START_PAYLOAD="$(python3 -c '
import json, sys
v = json.loads(sys.argv[1]); v["topic"] = sys.argv[2]; v["arguments"] = sys.argv[3]
print(json.dumps(v))
' "$VERSION_BLOB" "$TOPIC" "$ARGUMENTS")"
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_start "$START_PAYLOAD"
```

Log provider resolution once:

```bash
if [ ! -f "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged" ]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-providers.sh" || true
  touch "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged"
fi
```

### Step 5 — Notification policy

See [docs/human/config.md](docs/human/config.md) (notify.level key). Check via `config.py should-notify` before each push-notify call.

---

## Phase telemetry (mandatory)

At the **start** of each phase (0 through 4), record `T0=$(date +%s%3N)` and `USER_WAIT_MS_THIS_PHASE=0`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If a phase blocks on `AskUserQuestion`, log `user_wait_start` / `user_wait_end` events bracketing the wait:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
  '{"phase":<n>,"reason":"<short>"}'
_WAIT_T0=$(date +%s%3N)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
USER_WAIT_MS_THIS_PHASE=$(( USER_WAIT_MS_THIS_PHASE + $(date +%s%3N) - _WAIT_T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
  "$(printf '{"phase":<n>,"wall_ms":%d}' "$(( $(date +%s%3N) - _WAIT_T0 ))")"
```

---

## Phase 0 — Dispatch decision (intelligent, user-driven)

Record `T0=$(date +%s%3N)` and `USER_WAIT_MS_THIS_PHASE=0` at phase start.

### Step 1 — Read slug dir state

Compute `MAP_STATE` and `BRAINSTORM_STATE`:

**MAP_STATE algorithm:**

```bash
MAP_STATE="absent"
if [ -f "$Z_HARNESS_PLAN_DIR/MAP.md" ]; then
  # Read generated_at from MAP.md frontmatter
  MAP_GENERATED_AT="$(python3 -c "
import sys, re
with open(sys.argv[1]) as f:
    content = f.read()
m = re.search(r'^generated_at:\s*(.+)$', content, re.MULTILINE)
print(m.group(1).strip() if m else '')
" "$Z_HARNESS_PLAN_DIR/MAP.md")"

  if [ -z "$MAP_GENERATED_AT" ]; then
    MAP_STATE="stale"
  else
    # Check if any source file cited in MAP.md has a commit more recent than generated_at
    SOURCE_FILES="$(python3 -c "
import sys, re, json
with open(sys.argv[1]) as f:
    content = f.read()
m = re.search(r'^source_files:\s*\n((?:\s+-[^\n]+\n)*)', content, re.MULTILINE)
if not m:
    print('')
    sys.exit(0)
files = re.findall(r'-\s+(.+)', m.group(1))
print('\n'.join(f.strip() for f in files))
" "$Z_HARNESS_PLAN_DIR/MAP.md")"

    MAP_STATE="fresh"
    if [ -n "$SOURCE_FILES" ]; then
      while IFS= read -r src_file; do
        [ -z "$src_file" ] && continue
        COMMIT_TS="$(git log -1 --format=%cI -- "$src_file" 2>/dev/null || true)"
        if [ -n "$COMMIT_TS" ] && [ "$COMMIT_TS" \> "$MAP_GENERATED_AT" ]; then
          MAP_STATE="stale"
          break
        fi
      done <<< "$SOURCE_FILES"
    fi
  fi
fi
```

Note: untracked uncommitted changes in cited files are NOT counted as stale.

**BRAINSTORM_STATE algorithm:**

```bash
BRAINSTORM_STATE="absent"
if [ -f "$Z_HARNESS_PLAN_DIR/BRAINSTORM.md" ]; then
  BRAINSTORM_STATUS="$(python3 -c "
import sys, re
with open(sys.argv[1]) as f:
    content = f.read()
status_m = re.search(r'^status:\s*(.+)$', content, re.MULTILINE)
chosen_m = re.search(r'^chosen_(?:framing|pair):\s*(.+)$', content, re.MULTILINE)
status = status_m.group(1).strip() if status_m else ''
chosen = chosen_m.group(1).strip() if chosen_m else ''
print(status + '|' + chosen)
" "$Z_HARNESS_PLAN_DIR/BRAINSTORM.md")"

  STATUS_PART="$(echo "$BRAINSTORM_STATUS" | cut -d'|' -f1)"
  CHOSEN_PART="$(echo "$BRAINSTORM_STATUS" | cut -d'|' -f2)"

  if [ "$STATUS_PART" = "complete" ] && [ -n "$CHOSEN_PART" ] && [ "$CHOSEN_PART" != "abandoned" ]; then
    BRAINSTORM_STATE="complete"
  else
    BRAINSTORM_STATE="incomplete"
  fi
fi
```

### Step 2 — Dispatch decision matrix (4-bucket)

| MAP_STATE | BRAINSTORM_STATE | Suggested dispatch |
|---|---|---|
| `absent` or `stale` | `absent` or `incomplete` | **Run both** |
| `absent` or `stale` | `complete` | **Run /z-map, reuse BRAINSTORM** |
| `fresh` | `absent` or `incomplete` | **Reuse MAP, run /z-brainstorm** |
| `fresh` | `complete` | **Reuse both, synthesize directly** |

```bash
if [ "$MAP_STATE" = "absent" ] || [ "$MAP_STATE" = "stale" ]; then
  if [ "$BRAINSTORM_STATE" = "absent" ] || [ "$BRAINSTORM_STATE" = "incomplete" ]; then
    DISPATCH_SUGGESTION="run_both"
    DISPATCH_LABEL="Run both /z-map and /z-brainstorm"
  else
    DISPATCH_SUGGESTION="run_map_reuse_brainstorm"
    DISPATCH_LABEL="Run /z-map (MAP is ${MAP_STATE}), reuse existing BRAINSTORM"
  fi
else
  if [ "$BRAINSTORM_STATE" = "absent" ] || [ "$BRAINSTORM_STATE" = "incomplete" ]; then
    DISPATCH_SUGGESTION="reuse_map_run_brainstorm"
    DISPATCH_LABEL="Reuse existing MAP, run /z-brainstorm"
  else
    DISPATCH_SUGGESTION="reuse_both"
    DISPATCH_LABEL="Reuse both artifacts, go directly to synthesis panel"
  fi
fi
```

### Step 3 — AskUser dispatch gate

Log `user_wait_start`, then present via `AskUserQuestion`:

> **Dispatch decision for `/z-research $TOPIC`**
>
> Current artifact state:
> - MAP.md: `$MAP_STATE` (path: `$Z_HARNESS_PLAN_DIR/MAP.md`)
> - BRAINSTORM.md: `$BRAINSTORM_STATE` (path: `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`)
>
> Suggested dispatch: **$DISPATCH_LABEL**
>
> Options:
> 1. **Confirm suggested** (default)
> 2. **Override** (specify which sub-commands to run or skip — free text)
> 3. **Abandon** — exit without running anything

After user responds, set `DISPATCH_MAP` and `DISPATCH_BRAINSTORM` to one of `ran|reused|skipped|abandoned`:

- **Option 1:** resolve from `DISPATCH_SUGGESTION` (`run_both` → both `ran`, `run_map_reuse_brainstorm` → `ran/reused`, etc.)
- **Option 2:** parse user's free-text override; if ambiguous, AskUser again.
- **Option 3:** set both to `abandoned`, log `research_dispatch_decision` with abandoned status, emit `run_end status: aborted_by_user`, and exit.

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_dispatch_decision \
  "$(printf '{"map":"%s","brainstorm":"%s","map_state":"%s","brainstorm_state":"%s","suggestion":"%s"}' \
     "$DISPATCH_MAP" "$DISPATCH_BRAINSTORM" "$MAP_STATE" "$BRAINSTORM_STATE" "$DISPATCH_SUGGESTION")"
```

Log `phase_end` for Phase 0.

---

## Phase 0.5 — Cost gate

Record `T0=$(date +%s%3N)` and `USER_WAIT_MS_THIS_PHASE=0` at phase start.

### Step 1 — Estimate cost

```bash
COST_MAP=0
COST_BRAINSTORM=0
COST_PANEL=3000000   # 3 perspectives @ ~1M each
COST_JUDGE=500000    # judge @ ~0.5M

[ "$DISPATCH_MAP" = "ran" ] && COST_MAP=2000000
[ "$DISPATCH_BRAINSTORM" = "ran" ] && COST_BRAINSTORM=200000

COST_TOTAL=$(( COST_MAP + COST_BRAINSTORM + COST_PANEL + COST_JUDGE ))
COST_TOTAL_M="$(python3 -c "print(f'{$COST_TOTAL / 1_000_000:.1f}M')")"

COST_BREAKDOWN=""
[ "$DISPATCH_MAP" = "ran" ]        && COST_BREAKDOWN="$COST_BREAKDOWN /z-map: ~2M tokens |"
[ "$DISPATCH_BRAINSTORM" = "ran" ] && COST_BREAKDOWN="$COST_BREAKDOWN /z-brainstorm: ~200K tokens |"
COST_BREAKDOWN="$COST_BREAKDOWN synthesis panel (3 perspectives): ~3M tokens | judge: ~0.5M tokens"
```

### Step 2 — AskUser cost gate

Log `user_wait_start`, then present via `AskUserQuestion`:

> **Cost estimate for `/z-research $TOPIC`**
>
> Breakdown: $COST_BREAKDOWN
> **Total estimated: ~$COST_TOTAL_M tokens**
>
> Options:
> 1. **Proceed** — run as planned
> 2. **Change dispatch** — go back to Phase 0 to adjust which sub-commands to run
> 3. **Abandon** — exit cleanly, write nothing

Handle response:
- **Proceed:** log `research_cost_gate_decision {choice: proceed, estimated_tokens: $COST_TOTAL}` and continue.
- **Change dispatch:** log `research_cost_gate_decision {choice: change_dispatch, estimated_tokens: $COST_TOTAL}`, loop back to Phase 0. Cap at 3 loop-backs before falling through to Abandon.
- **Abandon:** log `research_cost_gate_decision {choice: abandon}`, emit `run_end status: aborted_by_user`, exit.

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_cost_gate_decision \
  "$(printf '{"choice":"%s","estimated_tokens":%d}' "<proceed|change_dispatch|abandon>" "$COST_TOTAL")"
```

Log `phase_end` for Phase 0.5.

---

## Phase 1 — Subcommand dispatch

Record `T0=$(date +%s%3N)` and `USER_WAIT_MS_THIS_PHASE=0` at phase start.

### Sub-run audit contract

The orchestrator cannot mutate a sub-command's internal RUN id. Audit attribution uses the **child-emits-event-with-parent-attribution** pattern:

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
2. Sub-command's Setup detects `$Z_HARNESS_PARENT_RUN_ID` and includes `parent_run_id` in every `log-event.sh` payload.
3. After the sub-command completes, orchestrator extracts the sub-run id from the sub-command's `run_start` event.
4. Orchestrator creates a symlink `archive/$RUN/subruns/<sub-command>` → `archive/<sub-run>/`.
5. Orchestrator emits `research_subcommand_complete`.

### Step 1 — Dispatch /z-map (if `DISPATCH_MAP=ran`)

If `DISPATCH_MAP=ran`:

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

   ```
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     subagent_type="z-map",
     description="Terrain mapping for /z-research: $TOPIC",
     prompt="$TOPIC --slug=$SLUG",
     env={
       "Z_HARNESS_PARENT_RUN_ID": "$RUN",
       "Z_HARNESS_PARENT_COMMAND": "/z-research"
     }
   )
   ```

2. After return, extract sub-run id:

   ```bash
   MAP_SUB_RUN="$(ls -1t "$Z_HARNESS_PLAN_DIR/archive/" | grep -v "^${RUN}$" | grep "$SLUG" | head -1 || true)"
   MAP_ARCHIVE_PATH="$Z_HARNESS_PLAN_DIR/archive/$MAP_SUB_RUN"
   ```

3. Verify MAP.md was written (file exists, size > 100 bytes, has `artifact:` field). If verification fails: abort, log `research_subcommand_failed {sub: z-map, reason: artifact_missing_or_malformed}`, push-notify. Do NOT attempt to fix the sub-command's output.

4. Create symlink and emit `research_subcommand_complete`.

If `DISPATCH_MAP=reused` or `DISPATCH_MAP=skipped`, emit `research_subcommand_complete` with the appropriate status.

### Step 2 — Dispatch /z-brainstorm (if `DISPATCH_BRAINSTORM=ran`)

If `DISPATCH_BRAINSTORM=ran`:

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

   ```
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     subagent_type="z-brainstorm",
     description="Brainstorm framings for /z-research: $TOPIC",
     prompt="$TOPIC --slug=$SLUG",
     env={
       "Z_HARNESS_PARENT_RUN_ID": "$RUN",
       "Z_HARNESS_PARENT_COMMAND": "/z-research"
     }
   )
   ```

2. After return, extract sub-run id (exclude `MAP_SUB_RUN`), create symlink, and verify BRAINSTORM.md (file exists, size > 100 bytes, has `artifact:` field). If verification fails: abort, log `research_subcommand_failed {sub: z-brainstorm, reason: artifact_missing_or_malformed}`, push-notify. Preserve partial artifacts already written.

3. Emit `research_subcommand_complete`.

If `DISPATCH_BRAINSTORM=reused` or `DISPATCH_BRAINSTORM=skipped`, emit accordingly.

### Step 3 — Final artifact readiness check

Before Phase 2, both MAP.md and BRAINSTORM.md must exist and be readable:

```bash
ARTIFACTS_READY=true
[ ! -f "$Z_HARNESS_PLAN_DIR/MAP.md" ]        && ARTIFACTS_READY=false
[ ! -f "$Z_HARNESS_PLAN_DIR/BRAINSTORM.md" ] && ARTIFACTS_READY=false

if [ "$ARTIFACTS_READY" = "false" ]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_end \
    "$(printf '{"slug":"%s","status":"aborted","reason":"required_artifacts_missing"}' "$SLUG")"
  exit 1
fi
```

Log `phase_end` for Phase 1.

---

## Phase 2 — Adversarial synthesis panel

Record `T0=$(date +%s%3N)` and `USER_WAIT_MS_THIS_PHASE=0` at phase start.

### Panel composition

Three perspectives dispatched in parallel via a **single message**:

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

**Invariant:** vendor assignments are static for vendor diversity. Do NOT substitute a hard-coded Opus call for an unavailable consultant — the vendor diversity is the point.

### Step 1 — Build shared panel prompt

```bash
PANEL_BASE_PROMPT="MODE: research-synthesis

host_run_id: $RUN
slug: $SLUG
topic: $TOPIC
map_path: $Z_HARNESS_PLAN_DIR/MAP.md
brainstorm_path: $Z_HARNESS_PLAN_DIR/BRAINSTORM.md

You are one perspective in an adversarial synthesis panel for /z-research. Analyze the approaches in BRAINSTORM.md against the terrain constraints in MAP.md from your assigned perspective lens.

HARD INVARIANTS:
- FORBIDDEN: proposing new design recommendations, new approaches, or new architectural patterns not already in BRAINSTORM.md.
- ALLOWED: scoring approaches against constraints, emphasizing constraints, noting contradictions, ranking by constraint-fit.
- Every claim must cite MAP.md or BRAINSTORM.md. Uncited claims are marked UNVERIFIED.
- NO recommendation language.

Your return MUST contain exactly these 4 sections:
## Approach scoring
## Constraint emphasis
## Contradictions noticed
## Citations"
```

Per-perspective addenda:

```bash
CONSERVATIVE_ADDENDUM="ASSIGNED PERSPECTIVE: architecture-conservative
Lens: lowest-risk implementation path; minimize MAP.md constraint violations. Cite per claim. Score and emphasize only."

EXPANSIVE_ADDENDUM="ASSIGNED PERSPECTIVE: product-expansive
Lens: most user-facing capability; which MAP.md constraints to relax. Cite per claim. Score and emphasize only."

ADVERSARIAL_ADDENDUM="ASSIGNED PERSPECTIVE: failure-mode-adversarial
Lens: what fails first in each framing; hidden coupling and debt per MAP.md constraints. Cite per claim. Score and emphasize only."
```

### Step 2 — Parallel dispatch (single message)

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  description="Panel: architecture-conservative for /z-research $SLUG",
  prompt="$PANEL_BASE_PROMPT\n\n$CONSERVATIVE_ADDENDUM")

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  description="Panel: product-expansive for /z-research $SLUG",
  prompt="$PANEL_BASE_PROMPT\n\n$EXPANSIVE_ADDENDUM")

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  description="Panel: failure-mode-adversarial for /z-research $SLUG",
  prompt="$PANEL_BASE_PROMPT\n\n$ADVERSARIAL_ADDENDUM")
```

Wait for all three before proceeding.

### Step 3 — Capture and handle failures

Write each successful return to `archive/$RUN/panel/<perspective>.md`.

**Failure semantics:**

A perspective fails if it errors, returns `bad_input`, times out, or returns a response missing all four required sections. Log each failure:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_panel_provider_unavailable \
  "$(printf '{"perspective":"%s","provider":"%s","reason":"%s"}' "<perspective>" "<provider>" "<reason>")"
```

- **1/3 fail:** proceed with surviving two. Judge handles `N=2` with `panel_degraded: true`.
- **2/3 fail:** AskUserQuestion with: **Retry** (default), **Proceed-with-1**, or **Abandon**. On retry: re-dispatch only failed perspectives. On abandon: log `run_end status: aborted_by_user`. Do not delete panel outputs.
- **3/3 fail:** hard halt. Log `total_panel_failure`, push-notify, exit. Do not write RESEARCH.md.

### Step 4 — Build perspectives array and emit telemetry

Build `PERSPECTIVES_JSON` containing only perspectives that succeeded (file exists, size > 50 bytes). For each, emit:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_panel_lane_complete \
  "$(printf '{"perspective":"%s","output_path":"%s"}' "<perspective>" "<path>")"
```

Log `phase_end` for Phase 2 with `perspective_count`.

---

## Phase 3 — Judge synthesis

Record `T0=$(date +%s%3N)` and `USER_WAIT_MS_THIS_PHASE=0` at phase start.

### Step 1 — Dispatch research-judge

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="research-judge",
  description="Final synthesis judge for /z-research $SLUG",
  prompt="host_run_id: $RUN
slug: $SLUG
perspectives: $PERSPECTIVES_JSON
map_path: $Z_HARNESS_PLAN_DIR/MAP.md
brainstorm_path: $Z_HARNESS_PLAN_DIR/BRAINSTORM.md
output_schema_version: 1

Follow your agent definition. Return the full RESEARCH.md content in your STATUS/RESEARCH_CONTENT block."
)
```

### Step 2 — Parse judge return

Parse structured return fields: `JUDGE_STATUS`, `JUDGE_PERSPECTIVE_COUNT`, `JUDGE_DEGRADED`, `JUDGE_TEMPTATION`, and `JUDGE_CONTENT` (extract from `RESEARCH_CONTENT:` block, strip fenced code block markers).

**Judge failure:** if `JUDGE_STATUS=unable_to_complete` or return is empty/malformed, log `research_judge_failed`, preserve all panel outputs, push-notify, surface to user, emit `run_end status: judge_failed` and exit.

### Step 3 — Compute source artifact metadata

```bash
MAP_SHA="$(git log -1 --format=%H -- "$Z_HARNESS_PLAN_DIR/MAP.md" 2>/dev/null || sha256sum "$Z_HARNESS_PLAN_DIR/MAP.md" | cut -d' ' -f1)"
BRAINSTORM_SHA="$(git log -1 --format=%H -- "$Z_HARNESS_PLAN_DIR/BRAINSTORM.md" 2>/dev/null || sha256sum "$Z_HARNESS_PLAN_DIR/BRAINSTORM.md" | cut -d' ' -f1)"
GENERATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

### Step 4 — Write RESEARCH.md atomically (tmp + rename)

Construct frontmatter with:

```yaml
---
artifact: research
artifact_kind: approach_synthesis
schema_version: 1
slug: <slug>
generated_at: <ISO-8601 UTC>
command: /z-research <arguments>
dispatch_decision:
  map: <ran|reused|skipped>
  brainstorm: <ran|reused|skipped>
source_artifacts:
  - path: MAP.md
    sha: <sha>
    generated_at: <map-generated-at>
  - path: BRAINSTORM.md
    sha: <sha>
    generated_at: <brainstorm-generated-at>
synthesizer_models:
  conservative: claude-opus
  expansive: codex (provider-resolved)
  adversarial: gemini (provider-resolved)
  judge: opus
panel_perspective_count: <N>
panel_degraded: <true|false>
status: complete
tripwires_fired: []
---
```

Then append `JUDGE_CONTENT`. Write to `.tmp` first, then `os.replace()` to final path.

### Step 5 — Emit `research_judge_complete` and log `phase_end` for Phase 3.

---

## Phase 4 — Finalize

Record `T0=$(date +%s%3N)` and `USER_WAIT_MS_THIS_PHASE=0` at phase start.

### Step 1 — Self-check RESEARCH.md

Validate RESEARCH.md contains required frontmatter fields and 10 mandatory body sections:

```
## Approach decision matrix
## Cross-artifact contradictions
## Design axes
## Terrain summary
## Brainstorm frame space
## High-leverage options
## Rejected / weak framings
## Evidence gaps
## Adversarial perspectives summary
## Mechanical rank-ordering
```

Also verify the decision matrix has at least 1 non-header data row.

If self-check fails: log `research_self_check_failed`, push-notify, surface to user. Preserve RESEARCH.md for debugging. Halt run.

### Step 2 — Automated tripwires (advisory — do NOT halt the run)

**Tripwire 1: `research_high_unverified_rate`** — if >50% of matrix cells are `UNVERIFIED`, log and add to `TRIPWIRES_FIRED`.

**Tripwire 2: `research_panel_degraded`** — if `PANEL_PERSPECTIVE_COUNT < 3`, log and add to `TRIPWIRES_FIRED`.

**Tripwire 3: `research_judge_temptation`** — if `JUDGE_TEMPTATION` is non-empty and not `none`, log and add to `TRIPWIRES_FIRED`.

### Step 3 — Update RESEARCH.md frontmatter with fired tripwires

If any tripwires fired, atomically update `tripwires_fired:` list in RESEARCH.md (tmp + rename).

### Step 4 — Post-launch tripwire notes (telemetry only, no automated action in v1)

T1–T4 require multiple production runs to evaluate; flag if observed post-run for a follow-up `/z-amend`.

### Step 5 — Push-notify + final message

```bash
[ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ] && \
  PushNotification("/z-research complete: $SLUG — RESEARCH.md written to $Z_HARNESS_PLAN_DIR/RESEARCH.md. Panel: $PANEL_PERSPECTIVE_COUNT/3 perspectives. Tripwires: ${TRIPWIRES_FIRED:-none}.")
```

Output final summary to user:

```
/z-research complete — $SLUG

RESEARCH.md: $Z_HARNESS_PLAN_DIR/RESEARCH.md
Panel perspectives: $PANEL_PERSPECTIVE_COUNT / 3
Dispatch: MAP=$DISPATCH_MAP, BRAINSTORM=$DISPATCH_BRAINSTORM
Tripwires fired: ${TRIPWIRES_FIRED:-none}

Recommended next: /z-plan <task> — RESEARCH.md will be consumed as canonical precontext (one-way gate active when artifact_kind: approach_synthesis + status: complete).
```

### Step 6 — Emit run_end

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":4,"name":"finalize","wall_ms":%d,"user_wait_ms":%d}' \
     "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"

bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_end \
  "$(printf '{"slug":"%s","status":"complete","research_md_path":"%s","panel_perspective_count":%d,"tripwires_fired":%s}' \
     "$SLUG" "$Z_HARNESS_PLAN_DIR/RESEARCH.md" "$PANEL_PERSPECTIVE_COUNT" \
     "$(echo "$TRIPWIRES_FIRED" | python3 -c 'import sys, json; print(json.dumps(sys.stdin.read().split()))' || echo '[]')")"
```

---

## Invariants

1. Produces ONLY `artifact_kind: approach_synthesis`. Never writes MAP.md or BRAINSTORM.md content directly — sub-commands own those artifacts.
2. Synthesis (research-judge AND panel perspectives) FORBIDDEN from proposing new design recommendations. Only collision-flagging, rank-ordering, and evidence-gap surfacing are allowed.
3. Every approach decision matrix cell MUST have either a citation OR be marked `UNVERIFIED`. No silent gaps.
4. Cost gate (Phase 0.5) ALWAYS runs before Phase 1 dispatch. No silent execution at 3–6M token scale.
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
6. Adversarial synthesis panel = 3 vendor-diverse perspectives. Vendor assignment static: `general-purpose` (Opus) = conservative, `consultant-primary` = expansive, `consultant-secondary` = adversarial. Judge always Opus.
7. Tripwires (Phase 4) are advisory only — they log events and warn but do NOT halt the run.
8. If MAP.md or BRAINSTORM.md is missing at Phase 2 start, halt immediately. Do not attempt synthesis without both source artifacts.
9. RESEARCH.md is written atomically (tmp + rename). A partial RESEARCH.md must never be left on disk.
10. Sub-command failure (Phase 1): abort current run; preserve partial artifacts; recommend user inspect + re-invoke. Do NOT attempt to fix inline.

## Error handling / edge cases

- **No topic at invocation:** AskUser gate in Setup Step 1. Never auto-invent a topic.
- **MAP.md without `artifact_kind` (legacy):** treat as `artifact_kind: map`. Log `legacy_map_artifact_detected`. Treat as stale for MAP_STATE.
- **Sub-command failure mid-dispatch:** abort Phase 1; preserve partial artifacts; surface to user; do not retry inline.
- **Panel returns fewer than 3 perspectives:** see Phase 2 failure semantics. Judge handles `N<3` with `panel_degraded: true`.
- **Judge failure or empty return:** halt Phase 3; preserve all panel outputs; surface to user.
- **Phase 0 loop-back from cost gate:** capped at 3 iterations before falling through to Abandon.
