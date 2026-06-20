---
name: z-brainstorm
disable-model-invocation: false
description: Cheap parallel pre-plan ideation — dispatch 3 vendor-diverse ideators (Claude + Codex + Gemini), perform a mandatory anti-bias check, and produce BRAINSTORM.md to seed /z-plan.
argument-hint: <topic to brainstorm> [--slug=<kebab>]
runtime: c1
driver_features_required:
  - subagent
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are running the **z-harness `/z-brainstorm`** pipeline.

Topic (from `$ARGUMENTS`):

$ARGUMENTS

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the question
     "What topic should I brainstorm?" via their native channel and accept a
     text reply. Silent omission is forbidden. -->
**If the topic above is empty or whitespace**, do this first: use `AskUserQuestion` to ask "What topic should I brainstorm?". Wait for their reply. Treat the reply as the topic and continue.

`/z-brainstorm` is **cheap, opt-in pre-planning**. It does not produce SPEC/PLAN/TASKS — those come from `/z-plan` later. Cost target: ≤200K tokens end-to-end. If you exceed that, log a warning and continue.

## Setup

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the slug
     confirmation question via their native channel if non-obvious. Silent
     omission is forbidden. -->
1. **Derive slug.** If `$ARGUMENTS` contains `--slug=<value>`, use that verbatim. Otherwise auto-derive from the topic: short kebab-case, 2-4 words (e.g. "rethink batting order model" → `rethink-batting-order`). If the auto-derived slug is non-obvious, confirm via `AskUserQuestion`.
2. **Export** `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")` for all subsequent shell calls and subagents.
3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the overwrite
     confirmation question (overwrite / abort) via their native channel when
     BRAINSTORM.md already exists. Silent omission is forbidden. -->
5. **Existing slug-dir handling.** Run `bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" all_plan_slugs` to check for existing slug names. If `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md` exists, prompt the user via `AskUserQuestion`:
   - **overwrite** — archive existing `BRAINSTORM.md` to `$Z_HARNESS_PLAN_DIR/archive/$RUN/BRAINSTORM.md.previous-<N>` (where `<N>` is the next free integer in that archive dir) and start fresh
   - **abort** — exit cleanly with no changes
6. **Version stamp + log run start:**
   ```bash
   export Z_HARNESS_SESSION_ID="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" session-id)"
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["topic"] = sys.argv[2]; v["session_id"] = sys.argv[3]; v["command"] = "z-brainstorm"
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>" "$Z_HARNESS_SESSION_ID")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" brainstorm_run_start "$START_PAYLOAD"
   ```
   **Run Brief init (immediately after `brainstorm_run_start`).** Registry: `/z-brainstorm`, profile `full`, artifact `BRAINSTORM.md` (`## User choice`).
   ```bash
   CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"
   RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
   BRAINSTORM_INTENT="<topic from $ARGUMENTS — max 240 chars; not the command name alone>"
   bash "$RB_SH" init --run "$RUN" --command /z-brainstorm --slug "$Z_HARNESS_SLUG" --profile full --intent "$BRAINSTORM_INTENT"
   export RUN_BRIEF_PROFILE=full
   export RUN_BRIEF_ARTIFACT="$Z_HARNESS_PLAN_DIR/BRAINSTORM.md"
   export RUN_BRIEF_ARTIFACT_FALLBACKS=""
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
9. **Cost guardrail.** Target ≤200K tokens. If the running total exceeds 200K (rough estimate: sum prompt+response chars across consult events ÷ 4), log a warning event and continue — do not halt.

**All paths live under `$Z_HARNESS_PLAN_DIR/`:**
- `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`
- `$Z_HARNESS_PLAN_DIR/archive/<RUN>/...`

## Phase 0 — Scope probe

Run Phase 0 **immediately after Setup** — BEFORE Plan Route Check, BEFORE Phase 1 scaffolding begins. scope-probe internally dispatches doc-fetcher (per its step 4); Phase 0 does not depend on Phase 1's doc-fetcher run.

### 0-sharpen. Sharpen-vs-skip gate (D5)

This is a **separate cheap check** that runs BEFORE scope-probe. It is NOT folded into scope-probe's LIGHT/MEDIUM/HEAVY classifier — the two checks are orthogonal (idea vagueness ≠ codebase fanout size).

**Check 1 — GRILL.md already exists?**

```bash
SHARPEN_GATE_DECISION=""
SHARPEN_GATE_REASON=""
GRILL_EXISTED=0
if [ -f "$Z_HARNESS_PLAN_DIR/GRILL.md" ]; then
  SHARPEN_GATE_DECISION="skip"
  SHARPEN_GATE_REASON="GRILL.md already exists for this slug"
  GRILL_EXISTED=1
fi
```

If a `GRILL.md` already exists for the slug, skip straight to the scope-probe (continue with step 0-count below). Phase 1c-ii already ingests `GRILL.md` as seed framing.

**Check 2 — Heuristic specificity check (if GRILL.md absent):**

Evaluate the topic for concreteness. A topic is **crisp** if it satisfies ALL of:
- Length > 20 characters (not a one-word stub)
- Contains at least one **concrete constraint or scope qualifier** (e.g. a file name, technology name, numbered target, time/size bound, or explicit "in X" / "for Y" clause)
- Is NOT purely abstract (e.g. "improve performance", "make it better", "ideas for the app")

If the heuristic result is unambiguous (clearly crisp OR clearly vague), set the decision directly. If the topic falls in a grey zone (e.g. 2-3 word phrase with no modifiers, medium length but no concrete scope), dispatch one Haiku call to resolve.

```bash
if [ -z "$SHARPEN_GATE_DECISION" ]; then
  TOPIC_LEN=${#TOPIC}   # TOPIC = the cleaned topic string from Setup
  # Heuristic: fast-path crisp if the topic looks sufficiently specific
  # (≥40 chars with at least one colon/slash/number/quoted term or file-ext pattern)
  if echo "$TOPIC" | grep -qE '(\.|/|:|[0-9]|"[^"]|`[^`])' && [ "$TOPIC_LEN" -ge 40 ]; then
    SHARPEN_GATE_DECISION="skip"
    SHARPEN_GATE_REASON="heuristic: topic has concrete markers and sufficient length"
  elif [ "$TOPIC_LEN" -lt 15 ]; then
    SHARPEN_GATE_DECISION="sharpen"
    SHARPEN_GATE_REASON="heuristic: topic is very short / likely a stub"
  fi
fi
```

If the heuristic left `SHARPEN_GATE_DECISION` empty (ambiguous topic), dispatch one Haiku call:

<!-- RUNTIME-GATE: subagent; non-supporting drivers skip this Agent() call and
     treat the result as SHARPEN_GATE_DECISION="skip" (conservative: don't
     force sharpening when the driver cannot run subagents). -->
```
Agent(
  subagent_type="general-purpose",
  model="haiku",
  description="Sharpen gate: evaluate topic specificity",
  prompt="Evaluate whether this brainstorm topic is CRISP (already names a concrete problem + constraints + scope) or VAGUE (abstract, stub, or missing key constraints).

Topic: <topic verbatim>

Respond with exactly two lines:
  DECISION: skip
  REASON: <one sentence>
or
  DECISION: sharpen
  REASON: <one sentence>

CRISP = names a concrete problem AND has at least one explicit constraint (technology, file/module, size limit, audience, or timeframe). VAGUE = missing the problem, missing constraints, or is a 1-3 word stub."
)
```

Parse the response and complete the gate:

```bash
if [ -z "$SHARPEN_GATE_DECISION" ]; then
  # Extract DECISION and REASON from the Haiku response stored in HAIKU_RESPONSE
  SHARPEN_GATE_DECISION="$(echo "$HAIKU_RESPONSE" | grep '^DECISION:' | head -1 | sed 's/^DECISION: *//' | tr -d '[:space:]')"
  SHARPEN_GATE_REASON="$(echo "$HAIKU_RESPONSE" | grep '^REASON:' | head -1 | sed 's/^REASON: *//')"
  # Fallback on parse failure: treat as skip (conservative — never force sharpening on bad parse)
  [ -z "$SHARPEN_GATE_DECISION" ] && SHARPEN_GATE_DECISION="skip" && SHARPEN_GATE_REASON="haiku parse failed — defaulting to skip"
fi
```

**Act on the decision:**

- **`skip`** — log the event and proceed to 0-count (count parse) → 0a (axis taxonomy) → 0b (fast-path check) → scope-probe as normal. Phase 1c-ii will still ingest any pre-existing GRILL.md.
- **`sharpen`** — auto-invoke z-sharpen inline before scope-probe:

  ```bash
  # Inline z-sharpen: run the sharpen conversation to produce GRILL.md
  # Z_HARNESS_PLAN_DIR and Z_HARNESS_SLUG are already exported from Setup.
  # z-sharpen writes $Z_HARNESS_PLAN_DIR/GRILL.md on convergence and exits.
  # "Inline" here means: reproduce the z-sharpen protocol in this same conversation
  # turn (no sub-agent dispatch, since z-sharpen is a c1 conversational command just
  # like z-brainstorm). Run the sharpen interview per commands/z-sharpen.md:
  #   Stage 1 — restate framing; Stage 2 — probe/reframe; Stage 3 — converge;
  #   Stage 4 — write GRILL.md.
  # The sharpen run emits its own sharpen_run_start / sharpen_convergence /
  # sharpen_run_end events (from z-sharpen's event schema).
  # After convergence, GRILL.md is present and Phase 1c-ii will ingest it as
  # seed framing. If the user abandons the sharpen interview, log the abandon
  # and continue without GRILL.md (treat as if SHARPEN_GATE_DECISION were "skip").
  SHARPEN_ABANDONED=0
  <run z-sharpen inline per commands/z-sharpen.md protocol>
  # On sharpen abandon: set SHARPEN_ABANDONED=1
  ```

  After inline z-sharpen completes (or the user abandons), proceed to 0-count → 0a → scope-probe.

**Emit `sharpen_gate` event regardless of decision:**

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" sharpen_gate \
  "$(python3 -c 'import json,sys; print(json.dumps({"decision":sys.argv[1],"reason":sys.argv[2],"grill_md_existed":sys.argv[3]=="1"}))' \
     "$SHARPEN_GATE_DECISION" "$SHARPEN_GATE_REASON" "${GRILL_EXISTED:-0}")"
```

---

### 0-count. Count parse (wide N)

Parse the desired ideator count `N` from the natural-language topic string. **No `--wide N` flag** — N is inferred from prose.

```bash
# Default N=3 (standard 3-vendor brainstorm)
WIDE_N=3

# Pattern-match the topic string for explicit count signals
TOPIC_LOWER="$(echo "$TOPIC" | tr '[:upper:]' '[:lower:]')"

# Explicit number: "8 ways", "10 options", "give me 5", "brainstorm 7", "×6", "x 6"
_EXPLICIT=$(echo "$TOPIC_LOWER" | grep -oE '[0-9]+\s*(ways?|options?|ideas?|framings?|ideators?|variants?)' | grep -oE '^[0-9]+' | head -1)
if [ -z "$_EXPLICIT" ]; then
  _EXPLICIT=$(echo "$TOPIC_LOWER" | grep -oE '(brainstorm|give me|~|about|roughly)\s*([0-9]+)' | grep -oE '[0-9]+' | head -1)
fi
if [ -z "$_EXPLICIT" ]; then
  _EXPLICIT=$(echo "$TOPIC_LOWER" | grep -oE '[0-9]+\s*x\b|\bx\s*[0-9]+' | grep -oE '[0-9]+' | head -1)
fi

if [ -n "$_EXPLICIT" ] && [ "$_EXPLICIT" -gt 1 ] 2>/dev/null; then
  WIDE_N="$_EXPLICIT"
else
  # Prose signals for "many": "lots of", "many", "wide", "mega", "as many as possible"
  if echo "$TOPIC_LOWER" | grep -qE '(lots of|a lot of|many options|many ways|wide mode|mega|as many as possible|maximum)'; then
    WIDE_N=6  # sensible default for "many"
  fi
fi

# Cap at a reasonable ceiling to prevent runaway token spend
if [ "$WIDE_N" -gt 20 ] 2>/dev/null; then
  WIDE_N=20
fi

# Telemetry record
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" count_parsed \
  "$(python3 -c 'import json,sys; print(json.dumps({"wide_n":int(sys.argv[1]),"default_used":sys.argv[1]=="3"}))' "$WIDE_N")"
```

Record `WIDE_N` for telemetry and for the D2 wide×HEAVY suppression check (step 0g). After count parse, continue to 0a (axis taxonomy) → 0b (fast-path check) → scope-probe.

---

### 0a. Define axis taxonomy

```
AXIS_TAXONOMY=["per_vendor","per_framing"]
```

This is the fixed brainstorm axis taxonomy for v1a. Pass it verbatim to scope-probe.

### 0b. Fast-path check (single-file target)

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
  PAYLOAD="$(python3 -c 'import json,sys; print(json.dumps({"command":sys.argv[1],"target":sys.argv[2],"arg_len":int(sys.argv[3])}))' "z-brainstorm" "$EXPANDED_ARG" "$ARG_LEN")"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_skipped_fast_path "$PAYLOAD"
  MODE=LIGHT
  AXIS=none
  CONFIDENCE=high
  REASON_CODES=fast_path_single_file
  REASON="single-file target auto-classified as LIGHT"
  chunks=[]
  seams_counted=0
  candidates_walked=0
  # Skip to 0e with LIGHT classification; do not dispatch scope-probe Agent.
  # Proceed directly to 0e — use the values above as if scope-probe returned STATUS=classified, MODE=LIGHT.
else
  # Multi-file / glob / large-arg path: run full scope-probe dispatch below.
fi
```

If the fast-path branch was taken (`SCOPE_FAST_PATH=1`), skip steps 0c and 0d (scope-probe dispatch and parse) and proceed directly to step 0e (treating the fast-path values as the parsed result).

### 0c. Dispatch scope-probe (non-fast-path only)

```
T0_PHASE0=$(date +%s%3N)
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_start \
  '{"host_command":"z-brainstorm","axis_taxonomy":["per_vendor","per_framing"]}'

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement and skip the scope-probe Agent() call. Default to MEDIUM mode. -->
Agent(
  subagent_type="scope-probe",
  description="Scope probe for z-brainstorm: <slug>",
  prompt="host_command: z-brainstorm
topic: <topic verbatim>
axis_taxonomy: [\"per_vendor\",\"per_framing\"]
repo_root: <abs path to repo root>
run_id: <RUN>"
)
```

### 0d. Parse scope-probe return

Parse the hybrid return using the two-step parser (line-prefix headers BEFORE the first ` ```json ` fence, JSON block via fence regex `^```json\n(.*?)^```$`). Extract:

- `STATUS` (classified | refused | bad_input)
- `MODE` (LIGHT | MEDIUM | HEAVY)
- `AXIS` (one of `per_vendor`, `per_framing`, or `none`)
- `CONFIDENCE` (high | medium | low)
- `REASON_CODES` (comma-separated string)
- `chunks` array from the fenced JSON block
- `seams_counted` and `candidates_walked` integers from the fenced JSON block

**Parser failure handling:** If the response is missing line-prefix headers, has no fenced JSON block, has malformed JSON, or has line-prefix headers inside the fence, emit `scope_probe_malformed` event with `{"host_command":"z-brainstorm","raw_response_len":<len>}`, treat as `STATUS: refused` + `MODE: MEDIUM`, and continue. Never retry.

**Low-confidence handling:** If `CONFIDENCE: low`, log a warning event (`scope_probe_low_confidence`), downgrade the result to `MODE: MEDIUM`, and continue. Do not AskUser in v1a.

### 0e. Write SCOPE artifacts (archive-first)

**Step 1 — Write archive copy first (must succeed):**

Assemble the SCOPE JSON from the parsed scope-probe return plus run-context metadata:

```json
{
  "host_command": "z-brainstorm",
  "slug": "<Z_HARNESS_SLUG>",
  "last_run_id": "<RUN>",
  "last_updated": "<UTC ISO 8601 timestamp>",
  "mode": "<MODE>",
  "axis": "<AXIS>",
  "confidence": "<CONFIDENCE>",
  "reason_codes": ["<code1>", "<code2>"],
  "chunks": [ ... ],
  "seams_counted": <int>,
  "candidates_walked": <int>,
  "scope_probe_version": "1"
}
```

Write atomically via tmp+rename to `$Z_HARNESS_PLAN_DIR/archive/$RUN/SCOPE.json`.

If the archive write fails: emit `scope_probe_archive_write_failed` event, skip Phase 0 entirely, and proceed to Plan Route Check as if scope-probe was never dispatched. Do not write the live file.

**Step 2 — Write live file (only after archive succeeds):**

Write the same JSON to `$Z_HARNESS_PLAN_DIR/SCOPE-brainstorm.json` atomically (tmp+rename). The live file is namespaced per host command; it is overwritten on each run.

### 0f. Log classification result

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_classified \
  "$(printf '{"host_command":"z-brainstorm","mode":"%s","axis":"%s","confidence":"%s","chunks_count":%d}' \
     "<MODE>" "<AXIS>" "<CONFIDENCE>" "<N chunks>")"
```

### 0g. Branch on STATUS, then MODE

**Branch on STATUS first:**

#### refused — MEDIUM fallback

If `STATUS: refused`: log a `scope_probe_refused` event, treat as `MODE: MEDIUM`, and proceed to Plan Route Check and then Phase 1 unchanged.

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_refused \
  '{"host_command":"z-brainstorm"}'
```

#### bad_input — MEDIUM fallback

If `STATUS: bad_input`: log a `scope_probe_bad_input` event, treat as `MODE: MEDIUM`, and proceed to Plan Route Check and then Phase 1 unchanged.

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_probe_bad_input \
  '{"host_command":"z-brainstorm"}'
```

**Only if `STATUS: classified`, branch on MODE:**

#### LIGHT or MEDIUM — pass-through

`MODE: LIGHT` or `MODE: MEDIUM`: proceed to Plan Route Check and then Phase 1 scaffolding unchanged. SCOPE-brainstorm.json is written but Phase 1 does not consult it for brainstorm (unlike `/z-audit` LIGHT, brainstorm has no `dimensions_hint` equivalent — Phase 1 runs identically for both modes in `/z-brainstorm`).

#### HEAVY — parallel sub-flow fan-out

When `MODE: HEAVY`:

**D2 — Wide-N × HEAVY suppression (check first, before any fan-out):**

If an explicit wide-N request was parsed in 0-count (i.e. `WIDE_N > 3`), suppress HEAVY chunk fanout and treat this run as MEDIUM instead. One fan-out axis at a time — wide and HEAVY never multiply.

```bash
if [ "${WIDE_N:-3}" -gt 3 ] 2>/dev/null; then
  # Wide request detected — HEAVY fanout suppressed (D2 invariant)
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" wide_suppressed_heavy \
    "$(python3 -c 'import json,sys; print(json.dumps({"requested_n":int(sys.argv[1]),"scope_mode":"HEAVY"}))' "$WIDE_N")"
  MODE=MEDIUM
  # Proceed to LIGHT/MEDIUM pass-through below — skip the HEAVY fan-out entirely
fi
```

If `WIDE_N > 3` triggered the suppression above, skip all remaining HEAVY steps and proceed to Plan Route Check and Phase 1 as if `MODE: MEDIUM`. The `wide_suppressed_heavy` event records the requested N and original scope classification for telemetry.

If `WIDE_N ≤ 3` (standard run, no explicit wide request), continue with HEAVY fan-out as normal:

1. **Log fan-out start:**
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_fanout_dispatched \
     "$(printf '{"host_command":"z-brainstorm","axis":"%s","chunks_count":%d}' "<AXIS>" "<N>")"
   ```

1a. **Soft cost estimate (non-blocking).** Call the gate helper with the HEAVY chunk count, display the estimate, and log the decision. This fires only here (HEAVY path); LIGHT/MEDIUM runs skip it entirely.
   ```bash
   # workflow.pre_run_cost_gate
   COST_GATE_JSON="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/pre-run-cost-gate.sh" \
     z-brainstorm soft "$RUN" --dispatch per_heavy_chunk=<N> 2>/dev/null)" || COST_GATE_JSON=""
   if [ -n "$COST_GATE_JSON" ]; then
     COST_HUMAN_BLOCK="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("human_block",""))' "$COST_GATE_JSON" 2>/dev/null || true)"
     [ -n "$COST_HUMAN_BLOCK" ] && printf '%s\n' "$COST_HUMAN_BLOCK"
     COST_ESTIMATED_TOKENS="$(python3 -c 'import json,sys; e=json.loads(sys.argv[1]).get("estimate",{}); print(json.dumps(e.get("estimated_tokens")))' "$COST_GATE_JSON" 2>/dev/null || echo "null")"
     COST_CONFIDENCE="$(python3 -c 'import json,sys; e=json.loads(sys.argv[1]).get("estimate",{}); print(e.get("confidence","unknown"))' "$COST_GATE_JSON" 2>/dev/null || echo "unknown")"
     COST_BASIS="$(python3 -c 'import json,sys; e=json.loads(sys.argv[1]).get("estimate",{}); print(e.get("basis","unknown"))' "$COST_GATE_JSON" 2>/dev/null || echo "unknown")"
   fi
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cost_gate_decision \
     "$(python3 -c 'import json,sys; print(json.dumps({"command":"z-brainstorm","choice":"auto_proceed","reason":"soft_gate","estimated_tokens":json.loads(sys.argv[1]),"confidence":sys.argv[2],"basis":sys.argv[3]}))' \
        "${COST_ESTIMATED_TOKENS:-null}" "${COST_CONFIDENCE:-unknown}" "${COST_BASIS:-unknown}")"
   ```

2. **Dispatch N parallel `/z-brainstorm` sub-flows** — one per chunk from the `chunks` array. Each sub-flow runs Phases 1 (scaffolding), 2 (ideator dispatch), and **3 (synthesis)** for its chunk's `scope_hint` sub-topic, producing its own per-chunk BRAINSTORM.md. Dispatch all N in a single message (parallel).

   For each chunk `C` in `chunks`, call:
   ```
   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
        requirement and skip all HEAVY sub-flow Agent() calls. Without subagent
        support the HEAVY path cannot proceed; default to MEDIUM mode. -->
   Agent(
     subagent_type="general-purpose",
     model="sonnet",
     description="z-brainstorm sub-flow for chunk <C.id>: <C.intent>",
     prompt="MODE: brainstorm-subflow

This is a HEAVY fan-out sub-flow of /z-brainstorm. Run Phase 1 (scaffolding), Phase 2 (ideator dispatch), and Phase 3 (synthesis) for the sub-scope below. Do NOT run Phase 0 (scope-probe), Plan Route Check, or Phase 4 (user-pick gate — selection happens at the parent level for HEAVY mode). Produce the per-chunk BRAINSTORM.md content; the parent orchestrator writes the file to the path below (you have no Write tool; return the full markdown in your response).

Z_HARNESS_PARENT_RUN_ID: <interpolate $RUN value here, e.g. 20260101T000000Z-my-slug>
Parent slug: <interpolate $Z_HARNESS_SLUG value here>
Chunk id: <C.id>
Sub-scope topic: <C.scope_hint> — <C.intent>
Original topic (for context): <topic>
Axis: <AXIS>
Output path: <interpolate $Z_HARNESS_PLAN_DIR>/archive/<interpolate $RUN>/chunks/<C.id>/BRAINSTORM.md

Scaffolding instructions: follow /z-brainstorm Phase 1 (doc-fetcher, optional Explore, MAP.md ingestion with legacy RESEARCH.md fallback, input_hash). Ideator dispatch: follow /z-brainstorm Phase 2 with the IDEATOR_SCHEMA. Synthesis: follow /z-brainstorm Phase 3 (anti-bias check, orchestrator recommendation). Return the full per-chunk BRAINSTORM.md content (frontmatter + body) with chosen_framing: pending in your response; the parent orchestrator writes the file. Do NOT present an AskUserQuestion — the parent owns the user-pick gate."
   )
   ```

   Sub-flows MUST NOT themselves go HEAVY (anti-sprawl invariant: sub-flows skip Phase 0 entirely).

3. **Collect sub-flow results and write per-chunk files.** Each sub-flow returns BRAINSTORM.md content as its response text (sub-agents have no Write tool — the orchestrator owns the write). For each chunk, write the returned text to `$Z_HARNESS_PLAN_DIR/archive/$RUN/chunks/<C.id>/BRAINSTORM.md` (atomic tmp+rename; create the parent dir first). Record:
   - `brainstorm_path`: `$Z_HARNESS_PLAN_DIR/archive/$RUN/chunks/<C.id>/BRAINSTORM.md`
   - `status`: succeeded (write completed, content is non-empty + has valid frontmatter) or failed (sub-flow errored or returned empty/malformed content)

4. **Dispatch scope-reconciler-brainstorm** to merge the per-chunk BRAINSTORM.md files. The reconciler is **read-only** — it returns merged BRAINSTORM.md text as its output; the orchestrator (/z-brainstorm) writes the file. Do NOT include `output_path` in the reconciler prompt.
   ```
   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
        requirement and skip the reconciler Agent() call. -->
   Agent(
     subagent_type="scope-reconciler-brainstorm",
     description="Reconcile HEAVY brainstorm chunks for <slug>",
     prompt="host_run_id: <interpolate $RUN value here>
chunks: <JSON array of {id, brainstorm_path, status?} — mark failed sub-flows with status: failed>
axis: <AXIS>"
   )
   ```

5. **Write unified BRAINSTORM.md.** Parse the text returned by scope-reconciler-brainstorm and write it to `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md` (the orchestrator performs this write, not the reconciler).

   If reconciler fails or returns no parseable content: fall back to concatenating the per-chunk BRAINSTORM.md files under a `## Reconciliation failed — raw chunks below` header, and write that to `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`.

6. **Log reconciliation:**
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" scope_fanout_reconciled \
     "$(printf '{"host_command":"z-brainstorm","axis":"%s","chunks_total":%d,"chunks_succeeded":%d,"reconciler_ok":%s}' \
        "<AXIS>" "<N>" "<succeeded_count>" "<true|false>")"
   ```

7. **Skip Phases 1, 2, and 3.** The unified BRAINSTORM.md (produced by the reconciler or the fallback) replaces the normal Phase 1+2+3 output. Jump directly to Phase 4 — **the HEAVY branch at the top of Phase 4 owns the chunk-selection matrix logic** (see Phase 4 HEAVY-mode branch above).

---

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check after Phase 1 scaffolding is assembled and before Phase 2 ideator dispatch. `/z-brainstorm` may route only before ideators are spawned; once ideation starts, finish the brainstorm flow instead of switching commands mid-run.

Use only already-known signals from the topic, doc-fetcher synthesis, optional Explore, and any ingested `MAP.md` (or legacy `RESEARCH.md` with `artifact_kind: map`): `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_existing_plan`, `plan_validation_intent`, `plan_amend_intent`, `has_fix_artifact`, and `docs_stale_or_drifted`. Set `plan_validation_intent`/`plan_amend_intent` only when the user re-enters a planning entry command on a slug with `SPEC.md`+`PLAN.md`+`TASKS.md` all present (see `agents/planning-router.md` for the language-match heuristic).

Deterministic routes:
- Route unknown terrain, missing citations, or insufficient source facts to `/z-research`.
- Route a framing that is already clear and ready for task planning to `/z-plan`.
- Route a small concrete fix (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`.
- Stay in `/z-brainstorm` when the terrain is known enough but multiple plausible framings remain.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

---

## Phase telemetry (mandatory)

At the **start** of each phase (1 through 4), record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If a phase blocks on `AskUserQuestion`, bracket the wait with `user_wait_start` / `user_wait_end` events so we can separate machine time from human-wait time:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
# ... AskUserQuestion ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
```

---

## Phase 1 — Scaffolding

Build a shared scaffolding payload that **all three ideators receive identically** (no read-by-reference asymmetry). Components:

### 1a. Doc-fetcher (if INDEX.json exists)

If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement and skip if unavailable. Brainstorm proceeds without doc grounding. -->
Agent(
  subagent_type="doc-fetcher",
  description="Doc context for <slug>",
  prompt="query: <one-sentence summary of the topic>\nrepo_root: <abs path>\ndepth: standard"
)
```

It returns a tight synthesis (matched concepts, key files with line ranges, invariants). If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed with empty doc synthesis. If it emits a `DRIFT WARNING`, log a `doc_drift` event per affected concept.

### 1b. Optional Explore

If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement and skip the Explore Agent() call. Step is optional. -->
Agent(
  subagent_type="Explore",
  model: "haiku",
  description="Brainstorm scaffolding for <slug>",
  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
)
```

If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.

### 1c. MAP.md ingestion

Resolve the terrain artifact to inline into scaffolding using this precedence:

1. **MAP.md (primary):** If `$Z_HARNESS_PLAN_DIR/MAP.md` exists, read it. This is the canonical terrain artifact after the `/z-research` → `/z-map` rename.
2. **Legacy RESEARCH.md fallback (backward-compat):** If MAP.md does not exist AND `$Z_HARNESS_PLAN_DIR/RESEARCH.md` exists, read its YAML frontmatter. Accept it as terrain scaffolding only if `artifact_kind` is `map` OR the `artifact_kind` field is absent (pre-rename legacy artifact). In that case, treat it identically to MAP.md.
3. **Explicit skip:** If `$Z_HARNESS_PLAN_DIR/RESEARCH.md` exists but its frontmatter has `artifact_kind: approach_synthesis`, **do not ingest it.** It is a synthesis output produced by the new `/z-research` meta-orchestrator — not raw terrain — and is not useful as brainstorm scaffolding. Log a note and proceed without terrain content.
4. **No terrain artifact:** If none of the above resolve, proceed with empty terrain content.

Once a terrain file is resolved (MAP.md or accepted legacy RESEARCH.md):

- **≤20 KB:** inline the full content into the scaffolding payload.
- **>20 KB:** produce an **extractive summary** that preserves citations and constraints (do not paraphrase; copy the cited bullets and constraint statements verbatim, drop the prose). Write the summary to `$Z_HARNESS_PLAN_DIR/archive/$RUN/research-summary-for-brainstorm.md`. Inline the summary instead of the full file.

Record `depends_on: [MAP.md]` in the eventual BRAINSTORM.md frontmatter if a terrain artifact was ingested (use the resolved filename — `MAP.md` or `RESEARCH.md` — as the value).

### 1c-ii. GRILL.md seed framing (if present)

If `$Z_HARNESS_PLAN_DIR/GRILL.md` exists, read it and extract two sections:

- `## Sharpened problem` — the refined problem statement from the grill interview
- `## Open branches` — unresolved decisions that remain after grilling

Inline both sections as **seed framing** in the scaffolding payload, placed after any terrain content. Prefix the block with a brief label so ideators understand its provenance:

```
--- GRILL.md seed framing ---
<contents of ## Sharpened problem section>

<contents of ## Open branches section>
--- end GRILL.md seed framing ---
```

If GRILL.md is absent, skip this step entirely — no placeholder, no warning. The seed framing is additive; it does not replace terrain content.

Record the GRILL.md content (the extracted two sections concatenated) in `GRILL_SEED_CONTENT` for use in the §1d input_hash computation.

### 1d. Assemble and hash

Compute the `input_hash` per SPEC:

```
input_hash = sha256(canonicalize(
    topic + "\n---\n" +
    doc_fetcher_synthesis_or_empty + "\n---\n" +
    explore_synthesis_or_empty + "\n---\n" +
    research_md_or_summary_or_empty + "\n---\n" +
    grill_seed_content_or_empty
)).hexdigest()[:16]
```

`grill_seed_content_or_empty` is the value of `GRILL_SEED_CONTENT` from §1c-ii, or an empty string if GRILL.md was absent. Including GRILL.md in the hash ensures that a changed GRILL.md invalidates any stale cache hit and forces brainstorm to regenerate.

`canonicalize`: strip leading/trailing whitespace; collapse all internal runs of whitespace to a single space.

Checkpoint: write the assembled scaffolding to `$Z_HARNESS_PLAN_DIR/archive/$RUN/phase1-scaffolding.md`.

---

## Phase 2 — Parallel ideator dispatch

### 2a. Resolve ideator personas

Gated on the `brainstorm.personas` config knob (default ON). **When the knob is OFF the entire block is a no-op** — every `*_PERSONA_PREFIX` stays empty and the dispatch in 2b is byte-identical to the pre-feature vendor-only brainstorm (no draw, no prefix, no `persona_bound` event). When ON, draw up to 3 **distinct** personas for the `ideator` role and prepend each persona body to one ideator's prompt — persona diversity layered on top of vendor diversity.

```bash
PLUGIN="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}"
USE_PERSONAS=$(python3 "$PLUGIN/scripts/config.py" get brainstorm.personas 2>/dev/null || echo "true")

# Vanilla defaults: empty prefix + "<none>" name for all three. Knob OFF leaves
# these untouched, so 2b dispatch is identical to the pre-persona behavior.
CLAUDE_PERSONA_PREFIX=""; CODEX_PERSONA_PREFIX=""; GEMINI_PERSONA_PREFIX=""
CLAUDE_PERSONA_NAME="<none>"; CODEX_PERSONA_NAME="<none>"; GEMINI_PERSONA_NAME="<none>"
CLAUDE_DRAW_ID=""; CODEX_DRAW_ID=""; GEMINI_DRAW_ID=""

if [ "$USE_PERSONAS" = "true" ]; then
  # Draw up to 3 distinct personas. GRACEFUL DEGRADATION: if the ideator pool has
  # fewer than 3 members, the subcommand returns a shorter array (or [] when empty)
  # and notes it on stderr — it never exits non-zero. Unfilled slots stay vanilla.
  PERSONAS_JSON=$(python3 "$PLUGIN/scripts/resolve-persona.py" random-distinct-for-role ideator --count=3 2>>"$Z_HARNESS_PLAN_DIR/archive/$RUN/persona-draw.log")

  # Positional bind: [0]->claude, [1]->codex, [2]->gemini. `// ""` yields an empty
  # string for absent indices under underflow, so those ideators run vanilla.
  for slot in 0:CLAUDE 1:CODEX 2:GEMINI; do
    idx="${slot%%:*}"; who="${slot##*:}"
    name=$(echo "$PERSONAS_JSON" | jq -r ".[$idx].persona // \"\"")
    path=$(echo "$PERSONAS_JSON" | jq -r ".[$idx].persona_body_path // \"\"")
    draw=$(echo "$PERSONAS_JSON" | jq -r ".[$idx].draw_id // \"\"")
    [ -z "$name" ] && continue   # underflow slot — leave vanilla
    # prepend_persona(path, "") strips frontmatter and returns "<body>\n\n".
    prefix=$(python3 "$PLUGIN/runtime/dispatch/persona_prompt.py" "$path" "" 2>/dev/null | head -c 4096)
    eval "${who}_PERSONA_NAME=\$name"
    eval "${who}_PERSONA_PREFIX=\$prefix"
    eval "${who}_DRAW_ID=\$draw"
  done
fi
```

**Emit `persona_bound` per ideator that received a persona** (attribution only — no outcome tracking; brainstorm ideators have no measurable terminal). Skip the emit for any vanilla slot and skip the whole step when the knob is OFF:

```bash
if [ "$USE_PERSONAS" = "true" ]; then
  for v in claude:CLAUDE codex:CODEX gemini:GEMINI; do
    vendor="${v%%:*}"; who="${v##*:}"
    eval "pname=\$${who}_PERSONA_NAME"; eval "pdraw=\$${who}_DRAW_ID"
    [ "$pname" = "<none>" ] && continue
    bash "$PLUGIN/scripts/log-event.sh" "$RUN" persona_bound \
      "$(python3 -c 'import json,sys; print(json.dumps({"command":"z-brainstorm","role":"ideator","vendor":sys.argv[1],"persona_id":sys.argv[2],"draw_id":sys.argv[3]}))' "$vendor" "$pname" "$pdraw")"
  done
fi
```

### 2b. Dispatch

Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.

Define a shared instruction block `IDEATOR_SCHEMA` (used verbatim in all three prompts):

```
Return exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point.
```

Then dispatch:

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip all three ideator Agent() calls. Phase 2
     cannot complete without subagent support. -->
Agent(
  subagent_type="general-purpose",
  model="sonnet",
  description="Claude ideator for <slug>",
  prompt="<CLAUDE_PERSONA_PREFIX>MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<paste assembled payload>\n\n<IDEATOR_SCHEMA>"
)
Agent(
  subagent_type="consultant-secondary",
  description="Codex ideator for <slug>",
  prompt="<CODEX_PERSONA_PREFIX>MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>\n\n<IDEATOR_SCHEMA>"
)
Agent(
  subagent_type="consultant-primary",
  description="Gemini ideator for <slug>",
  prompt="<GEMINI_PERSONA_PREFIX>MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>\n\n<IDEATOR_SCHEMA>"
)
```

Each `<*_PERSONA_PREFIX>` is the persona body followed by a blank line (from 2a), or **empty** when that ideator drew no persona (underflow slot) or the `brainstorm.personas` knob is OFF — in the empty case the prompt is byte-identical to the pre-persona dispatch. All three ideators still see byte-identical **scaffolding** and **schema** instructions; only the persona prefix differs, which is the entire point — persona diversity on top of vendor diversity. The persona is a **prompt-prefix only**: model and runtime per ideator are unchanged. The consultants return RAW (per the `MODE: brainstorm` contract in their agent files) — no standard wrapper. The Claude ideator (general-purpose Sonnet) returns the same five-section block.

### Ideator failure policy

Treat an ideator as failed if it returns an error, times out, or returns no parseable five-section block.

- **1/3 fail** → proceed with the surviving two. Record the failed member as `"<id>:failed"` in the `ideators` frontmatter list using the canonical id (`claude:failed` | `codex:failed` | `gemini:failed`). The Phase 3 anti-bias check becomes a two-way comparison (still mandatory). Log `ideator_failed` with `{vendor, reason}`.
<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the 2/3 ideator
     failure gate (retry / proceed-with-1 / abandon) via their native channel.
     Silent omission is forbidden. -->
- **2/3 fail** → halt. Use `AskUserQuestion` with options:
  - **retry** (default) — re-dispatch the failed ideators once
  - **proceed-with-1** — record the two failed members and run Phase 3 with a single framing (anti-bias check becomes "single framing — no comparison possible; flag inherent bias risk")
  - **abandon** — write a minimal abandoned BRAINSTORM.md (frontmatter: `artifact`, `slug`, `generated_at`, `command`, `input_hash`, `ideators` with `:failed` suffix on the failed members, `ideator_models`, `status: abandoned`, `chosen_framing: abandoned`; body: a single `## Abandoned` section with one sentence of context) so `/z-plan` can detect the prior attempt, then run **Run Brief — halt finalize** below (substitute `<reason>` = `abandoned after ideator failures`), exit.
- **3/3 fail** → hard halt. Log `total_ideator_failure`, run **Run Brief — halt finalize** below (substitute `<reason>` = `all three ideators failed`), exit. Do not write BRAINSTORM.md.

Log every individual failure as `ideator_failed` regardless of the bucket above.

---

### 2c. Wide mode dispatch (WIDE_N > 3)

This section fires **only when `WIDE_N > 3`** (set in Phase 0 step 0-count). When `WIDE_N ≤ 3`, skip this entire section — the Phase 2b dispatch above is the complete ideator path.

#### 2c-0. Overflow model resolution

Resolve the model to use for overflow waves (waves 2+). Resolution order: **prompt override > config knob > default (`haiku`)**.

```bash
PLUGIN="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}"

# Step 1: check for prompt-level override (set by the user in $ARGUMENTS, e.g. "--overflow-model=sonnet")
OVERFLOW_MODEL_OVERRIDE=""
if echo "${ARGUMENTS:-}" | grep -qE '\-\-overflow-model=\S+'; then
  OVERFLOW_MODEL_OVERRIDE="$(echo "${ARGUMENTS:-}" | grep -oE '\-\-overflow-model=\S+' | head -1 | sed 's/--overflow-model=//')"
fi

# Step 2: read config knob brainstorm.wide_overflow_model (T004)
OVERFLOW_MODEL_CONFIG="$(python3 "$PLUGIN/scripts/config.py" get brainstorm.wide_overflow_model 2>/dev/null || echo "")"
[ -z "$OVERFLOW_MODEL_CONFIG" ] && OVERFLOW_MODEL_CONFIG="haiku"

# Step 3: resolve (prompt override wins)
if [ -n "$OVERFLOW_MODEL_OVERRIDE" ]; then
  OVERFLOW_MODEL="$OVERFLOW_MODEL_OVERRIDE"
else
  OVERFLOW_MODEL="$OVERFLOW_MODEL_CONFIG"
fi

# cheap-mixed gating (M2): no --model mechanism exists in resolve-provider.py / providers.json
# for codex-cli or agy today. If the config resolves to "cheap-mixed", warn and fall back to haiku.
if [ "$OVERFLOW_MODEL" = "cheap-mixed" ]; then
  bash "$PLUGIN/scripts/log-event.sh" "$RUN" wide_overflow_model_warn \
    '{"reason":"cheap-mixed requested but no --model path verified for codex-cli/agy; falling back to haiku","config_value":"cheap-mixed"}'
  # Warn the user inline:
  echo "⚠ wide_overflow_model=cheap-mixed is not yet implemented (no --model path verified for codex-cli/agy). Overflow ideators will use haiku instead. Set brainstorm.wide_overflow_model=haiku or an explicit Claude model string to suppress this warning." >&2
  OVERFLOW_MODEL="haiku"
fi
# An explicit Claude model string (e.g. "sonnet") IS honored for general-purpose overflow ideators.
```

#### 2c-1. Conversational cost gate

Before dispatching a wide run, present a cost estimate inline and **end the turn** — this is a conversational gate, NOT an `AskUserQuestion`. Wait for the user's natural-language go-ahead before proceeding.

Compute an estimate:
- Wave 1: 3 ideators × ~3,000 tokens each = ~9,000 tokens
- Each overflow wave: 2 ideators × ~3,000 tokens = ~6,000 tokens per wave
- Overflow waves needed: `OVERFLOW_N = WIDE_N - 3` ideators → `ceil(OVERFLOW_N / 2)` waves (each wave has 2 ideators)
- Clusterer: ~2,000 tokens

```bash
OVERFLOW_N=$(( WIDE_N - 3 ))
OVERFLOW_WAVES=$(( (OVERFLOW_N + 1) / 2 ))   # ceil(OVERFLOW_N / 2)
EST_TOKENS=$(( 9000 + OVERFLOW_WAVES * 6000 + 2000 ))
```

Present inline in your response and **stop — end the turn here**:

> **Wide brainstorm: `<slug>`**
>
> You requested **`<WIDE_N>` ideators**. Here's what this will dispatch:
> - Wave 1: 3 vendor-diverse ideators (Claude / Codex / Gemini) at normal models
> - `<OVERFLOW_WAVES>` overflow wave(s): `<OVERFLOW_N>` additional ideator(s) at `<OVERFLOW_MODEL>` using anti-seeded divergent axes
> - After all waves: `ideator-clusterer` (Haiku) to collapse N framings → K distinct directions
>
> Estimated tokens: ~`<EST_TOKENS>` (rough; actual varies by payload size).
>
> Proceed? (Reply "yes" / "go" / "proceed" to start, or name a smaller N to reduce cost.)

**HARD INVARIANT:** Do NOT dispatch any ideators until the user confirms. The orchestrator must stop here and await the user's reply. If the user replies with a smaller N or any modification, update `WIDE_N` accordingly and recompute before proceeding.

On user go-ahead, continue to 2c-2.

#### 2c-2. Emit `wide_dispatch` event

```bash
bash "$PLUGIN/scripts/log-event.sh" "$RUN" wide_dispatch \
  "$(python3 -c 'import json,sys; print(json.dumps({"wide_n":int(sys.argv[1]),"waves":int(sys.argv[2])+1,"overflow_model":sys.argv[3]}))' \
     "$WIDE_N" "$OVERFLOW_WAVES" "$OVERFLOW_MODEL")"
```

The `waves` field counts all waves including wave 1 (= `OVERFLOW_WAVES + 1`).

#### 2c-3. Wave 1 — 3 vendors at normal models

Wave 1 is the existing 3-vendor Phase 2b dispatch (Claude/Codex/Gemini at their normal models). The Phase 2a persona resolution and 2b dispatch already ran above — the results are wave 1 framings. Treat them as such.

Track all ideator IDs for clustering:

```bash
# After Phase 2b dispatch completes, record wave-1 ideator IDs
WIDE_IDEATOR_IDS='["claude-wave1","codex-wave1","gemini-wave1"]'
WIDE_WAVES_COMPLETED=1

# Append wave-1 framing blocks to BRAINSTORM.md under a wave header.
# BRAINSTORM.md is written in Phase 3 normally; for wide mode, the Phase 3 write
# must label each wave-1 framing block with its wave provenance for the clusterer.
# Specifically: prepend a "## Wave 1" header before the ## Framing: <ideator> blocks
# in BRAINSTORM.md when WIDE_N > 3. The clusterer reads the full file.
WIDE_WAVE1_HEADER="## Wave 1"
```

Write the `## Wave 1` header before the per-ideator framing blocks in BRAINSTORM.md (in Phase 3's write step). The clusterer uses this to locate all wave framings in the file.

#### 2c-4. Overflow waves (waves 2+)

For each overflow ideator batch, invoke the **Re-spin machinery** (see `### Re-spin machinery` section) with:

- `RESPIN_DIRECTION` = "Wide-mode overflow: produce a framing that diverges from all prior framings on a different axis (different core hypothesis, different problem decomposition, different target user, or different solution lever)."
- `RESPIN_WAVE` = current wave number (starting at 1 for first overflow wave, capped at 3 — re-spin machinery cap applies to the discussion loop; for wide-mode overflow waves we use separate tracking below)
- `RESPIN_PRIOR_FRAMINGS` = all framing blocks returned so far (initially the wave-1 blocks)

**Wide-mode overflow wave tracking** (separate from the discussion-loop re-spin cap):

```bash
# Overflow wave tracking (wide mode only — separate from discussion-loop re-spin cap)
OVERFLOW_REMAINING=$OVERFLOW_N    # number of overflow ideators still to dispatch
OVERFLOW_WAVE_NUM=1               # wave number within overflow (1-indexed; maps to RESPIN_WAVE 1, 2, 3)
```

For each overflow wave:

1. Determine vendor subset from re-spin machinery (wave number determines subset deterministically):
   - Overflow wave 1 → Claude + Codex
   - Overflow wave 2 → Claude + Gemini
   - Overflow wave 3 → Codex + Gemini (cap at 3 overflow waves; N>9 rare but cap enforced)

2. Resolve overflow model for these ideators. If `OVERFLOW_MODEL` is `haiku` or an explicit Claude model string, use it for the `general-purpose` slot. The consultant arms (codex/gemini) use their native defaults (no `--model` override) — this is the M2 constraint.

   ```
   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
        requirement to the user and skip the overflow ideator Agent() calls.
        Wide-mode overflow cannot complete without subagent support. -->
   ```

   **Overflow wave dispatch** (example for overflow wave 1 — Claude + Codex):

   Resolve a **distinct persona** for each overflow ideator slot (draw from the ideator pool, excluding personas already used in prior waves):

   ```bash
   # Draw N_TOTAL = WIDE_N distinct personas total (all waves), using --count=WIDE_N.
   # Wave 1 used slots [0..2]; overflow wave k uses the next available slots.
   # If the pool underflows, remaining overflow slots run vanilla (no persona).
   OVERFLOW_PERSONAS_JSON=$(python3 "$PLUGIN/scripts/resolve-persona.py" \
     random-distinct-for-role ideator --count="$WIDE_N" \
     2>>"$Z_HARNESS_PLAN_DIR/archive/$RUN/persona-draw.log")
   # Slot index for overflow ideator i (0-indexed across overflow waves):
   #   slot_index = 3 + i   (wave-1 used slots 0,1,2)
   ```

   Build the anti-seed payload (per re-spin machinery template — divergence instruction verbatim):

   ```
   <OVERFLOW_PERSONA_PREFIX>
   MODE: brainstorm

   Topic: <topic>

   Narrowed direction from the user: Wide-mode overflow: produce a framing that diverges from all prior framings on a different axis (different core hypothesis, different problem decomposition, different target user, or different solution lever).

   Here are the existing framings from this brainstorm run:

   <RESPIN_PRIOR_FRAMINGS>

   Produce something that diverges from all of them — attack a different axis (different core hypothesis, different problem decomposition, different target user, or different solution lever). Do NOT restate, synthesize, or incrementally improve an existing framing. The goal is genuine divergence.

   <IDEATOR_SCHEMA>
   ```

   **For overflow wave 1 (Claude + Codex):**
   ```
   Agent(
     subagent_type="general-purpose",
     model="<OVERFLOW_MODEL>",
     description="Claude overflow ideator wave <OVERFLOW_WAVE_NUM> for <slug>",
     prompt="<overflow anti-seed prompt for Claude, per template above>"
   )
   Agent(
     subagent_type="consultant-secondary",
     description="Codex overflow ideator wave <OVERFLOW_WAVE_NUM> for <slug>",
     prompt="<overflow anti-seed prompt for Codex, per template above>"
   )
   ```

   **For overflow wave 2 (Claude + Gemini):**
   ```
   Agent(
     subagent_type="general-purpose",
     model="<OVERFLOW_MODEL>",
     description="Claude overflow ideator wave <OVERFLOW_WAVE_NUM> for <slug>",
     prompt="<overflow anti-seed prompt for Claude>"
   )
   Agent(
     subagent_type="consultant-primary",
     description="Gemini overflow ideator wave <OVERFLOW_WAVE_NUM> for <slug>",
     prompt="<overflow anti-seed prompt for Gemini>"
   )
   ```

   **For overflow wave 3 (Codex + Gemini, no Claude):**
   ```
   Agent(
     subagent_type="consultant-secondary",
     description="Codex overflow ideator wave 3 for <slug>",
     prompt="<overflow anti-seed prompt for Codex>"
   )
   Agent(
     subagent_type="consultant-primary",
     description="Gemini overflow ideator wave 3 for <slug>",
     prompt="<overflow anti-seed prompt for Gemini>"
   )
   ```

   Note: `OVERFLOW_MODEL` applies **only to the `general-purpose` (Claude) slot**. Consultant arms (codex/gemini) run at their native defaults — M2 constraint: no `--model` path exists for codex-cli or agy.

3. After each overflow wave returns, append framing blocks to BRAINSTORM.md under a `## Wave <N>` header:

   ```markdown

   ## Wave <WAVE_NUM>

   <!-- overflow ideators: <list>; persona: <ids or none>; failed: <list or "none"> -->

   ### Framing — <ideator-id> (wave <WAVE_NUM>)

   <five-section block from ideator, verbatim>

   ### Framing — <ideator-id> (wave <WAVE_NUM>)

   <five-section block from second ideator, if surviving>
   ```

4. Update tracking:

   ```bash
   # Record ideator IDs for clustering
   WIDE_IDEATOR_IDS="$(python3 -c "import json,sys; ids=json.loads(sys.argv[1]); ids+=['<vendor1>-wave<N>','<vendor2>-wave<N>']; print(json.dumps(ids))" "$WIDE_IDEATOR_IDS")"
   OVERFLOW_REMAINING=$(( OVERFLOW_REMAINING - 2 ))   # or -1 if 1 ideator dispatched in final partial wave
   OVERFLOW_WAVE_NUM=$(( OVERFLOW_WAVE_NUM + 1 ))
   WIDE_WAVES_COMPLETED=$(( WIDE_WAVES_COMPLETED + 1 ))
   ```

5. Update `RESPIN_PRIOR_FRAMINGS` to include the new wave's blocks before dispatching the next overflow wave.

6. Stop dispatching overflow waves when `OVERFLOW_REMAINING ≤ 0` or `OVERFLOW_WAVE_NUM > 3` (cap: max 3 overflow waves regardless of N; for N > 9, the extra ideators are silently capped and the user is informed).

**Cap notification:** If `WIDE_N > 9` (more than 3 overflow waves would be needed), inform the user inline before dispatching: "Wide cap: dispatching up to 9 ideators across 4 waves (1 base + 3 overflow). Your requested N=`<WIDE_N>` exceeds the overflow cap — proceeding with N=9."

Apply the same failure policy as the re-spin machinery: 1/2 fail → proceed with survivor; 2/2 fail → log and continue (does not decrement cap). Log each failure as `ideator_failed` with `{vendor, reason, wave: <wave_num>}`.

#### 2c-5. Dispatch ideator-clusterer

After all waves (wave 1 + all overflow waves) return:

1. Ensure BRAINSTORM.md is written with all wave framing blocks (Phase 3 writes wave-1 blocks; overflow blocks appended in 2c-4). The file is the clusterer's source of truth.

2. Collect the ordered list of all ideator IDs across all waves into `WIDE_IDEATOR_IDS` (already tracked above).

3. Dispatch the clusterer:

   ```
   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
        requirement and skip the clusterer Agent() call. Fall back to presenting
        raw N framings in the Phase 3 briefing. -->
   Agent(
     subagent_type="ideator-clusterer",
     description="Cluster <WIDE_N> wide-mode framings for <slug>",
     prompt="brainstorm_path: <abs path to $Z_HARNESS_PLAN_DIR/BRAINSTORM.md>
   ideator_ids: <WIDE_IDEATOR_IDS as JSON array>
   n: <WIDE_N>"
   )
   ```

4. Parse the clusterer's returned text. Extract:
   - `K` — number of distinct clusters (from the `K: <n>` line in `## Effective-diversity report`)
   - The `## Clusters` section — K cluster labels, members, representative framings
   - The `## Cross-cluster consensus` section (may be "None detected.")
   - The `## Clusterer note` paragraph

   Store these as `CLUSTER_REPORT`, `CLUSTER_K`, and `CLUSTER_BLOCKS` for use in the Phase 3 ranked briefing.

5. **Clusterer failure handling:** If the clusterer fails or returns K=0, fall back to presenting the N raw framings directly in the Phase 3 briefing (set `CLUSTER_REPORT=""` and `CLUSTER_K=0` as the fallback signal).

After 2c-5, proceed to Phase 3. Phase 3's ranked briefing uses `CLUSTER_BLOCKS` when `WIDE_N > 3` and `CLUSTER_K > 0` (wide mode), or falls back to raw framings (narrow mode or clusterer failure).

---

## Phase 3 — Synthesis + mandatory anti-bias check

1. **Parse** the three (or two, or one) returns. For each ideator, extract the five sections. If a section is missing or malformed, record it as `<missing>` rather than omitting it.

2. **Anti-bias check (MANDATORY).** Section-by-section, compare what each ideator said and identify which framing wins that dimension. **If you (the orchestrator, running on Claude) find yourself picking the Claude ideator over a peer for a given section, you must write an explicit justification for that pick.** "Claude wins" without justification is not acceptable — every Claude-favoring call needs a concrete reason (e.g. "Claude wins on Risks because it surfaced the data-leakage edge case that Codex and Gemini missed"). For two-way comparisons (one ideator failed), the same rule applies.

3. **Orchestrator recommendation.** Pick one framing as your tentative recommendation with a one-line rationale. The user is free to override.

4. **Write `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`** with YAML frontmatter:

   **Narrow mode (`WIDE_N ≤ 3`) frontmatter:**

   ```yaml
   ---
   artifact: brainstorm
   slug: <slug>
   generated_at: <UTC ISO 8601>
   command: /z-brainstorm <args>
   input_hash: <16 hex from Phase 1d>
   depends_on: [<MAP.md or RESEARCH.md if terrain artifact ingested — use actual resolved filename>]
   ideators:
     - claude
     - codex
     - gemini
     # failed members recorded as "<id>:failed" (e.g. claude:failed)
   ideator_models:
     claude: sonnet
     codex: default
     gemini: default
   ideator_personas:        # persona bound to each ideator (brainstorm.personas knob)
     claude: <persona-id or "<none>">   # "<none>" = vanilla (knob OFF or underflow slot)
     codex: <persona-id or "<none>">
     gemini: <persona-id or "<none>">
   status: complete
   chosen_framing: pending
   ---
   ```

   **Wide mode (`WIDE_N > 3`) frontmatter:** add `wide_n` and `overflow_model` fields; `ideators` lists all wave members with their wave suffix; `ideator_models` records `overflow: <OVERFLOW_MODEL>` for the overflow slots.

   ```yaml
   ---
   artifact: brainstorm
   slug: <slug>
   generated_at: <UTC ISO 8601>
   command: /z-brainstorm <args>
   input_hash: <16 hex from Phase 1d>
   depends_on: [<resolved filename if terrain>]
   wide_n: <WIDE_N>
   overflow_model: <OVERFLOW_MODEL>
   ideators:
     - claude-wave1
     - codex-wave1
     - gemini-wave1
     - claude-wave2    # overflow ideators follow
     - codex-wave2
     # failed members: "<id>:failed"
   ideator_models:
     wave1_claude: sonnet
     wave1_codex: default
     wave1_gemini: default
     overflow: <OVERFLOW_MODEL>   # all overflow Claude slots use this
   ideator_personas:
     claude-wave1: <persona-id or "<none>">
     codex-wave1: <persona-id or "<none>">
     gemini-wave1: <persona-id or "<none>">
     # overflow slots: <ideator-id>: <persona-id or "<none>">
   status: complete
   chosen_framing: pending
   ---
   ```

   `ideator_personas` records the distinct persona drawn for each ideator (the `*_PERSONA_NAME` values from Phase 2a). A value of `<none>` means that ideator ran vanilla — either the `brainstorm.personas` knob was OFF, or the ideator pool underflowed and this slot got no persona. When an ideator also failed, its persona binding is still recorded here even though the member appears as `<id>:failed` in `ideators`.

   `chosen_framing` is written as `pending` here and updated in Phase 4 to one of `claude | codex | gemini | synthesized | restart | abandoned` per SPEC. `synthesized` is the default/expected outcome for a discussion-born hybrid framing co-authored with the user.

   Body sections, one block per ideator (in fixed order Claude → Codex → Gemini):

   **Narrow mode (`WIDE_N ≤ 3`):** write framing blocks directly at the top level.

   ```markdown
   ## Framing: <ideator-name>

   ### Framing
   <one paragraph or `<missing>`>

   ### Core hypothesis
   <one paragraph or `<missing>`>

   ### Risks
   <bulleted list or `<missing>`>

   ### Plan implications
   <bulleted list or `<missing>`>

   ### What would change my mind
   <bulleted list or `<missing>`>
   ```

   **Wide mode (`WIDE_N > 3`):** prefix the wave-1 framing blocks with a `## Wave 1` header so the clusterer can locate all waves consistently. Overflow wave blocks are already appended under `## Wave <N>` headers in Phase 2c-4.

   ```markdown
   ## Wave 1

   ## Framing: claude-wave1

   ### Framing
   <one paragraph or `<missing>`>
   ...

   ## Framing: codex-wave1
   ...

   ## Framing: gemini-wave1
   ...
   ```

   Followed by (both narrow and wide modes):

   ```markdown
   ## Anti-bias check
   <section-by-section comparison with explicit justification for any Claude-favoring pick>

   ## Orchestrator recommendation
   <one-line rationale; user is free to override>
   ```

   Do **not** write a `## User choice` section in Phase 3 — Phase 4 writes it for the first time (no placeholder, no duplication).

5. **Produce a ranked prose briefing and end the turn.** Do NOT use `AskUserQuestion` here. Do NOT call any further tool. Present the ranked briefing in-line and stop — the orchestrator must wait for the user's natural-language reply.

   **Ranked briefing format** (write this directly in your response):

   > **Brainstorm complete — `<slug>`**
   >
   > Here are the **<N> directions**, ranked by strength:
   >
   > **1. <direction label> (e.g. Claude framing)**
   > - **Pros:** <2-3 bullets>
   > - **Cons:** <2-3 bullets>
   >
   > **2. <direction label>**
   > - **Pros:** <2-3 bullets>
   > - **Cons:** <2-3 bullets>
   >
   > *(repeat for each available framing in ranked order)*
   >
   > **Consensus:** <one sentence on where all ideators agree — call it a signal, not a waste>
   >
   > **Divergence:** <one sentence on the genuine decision point — what the framings disagree on>
   >
   > **My recommendation:** <framing label> — <one-sentence rationale>
   >
   > What direction do you want to go? You can pick one as-is, ask me to defend a choice, combine ideas, request a re-spin (see [re-spin machinery]), or restart/abandon.

   Ranking criteria: favor the framing with the most concrete plan implications and lowest risk exposure, adjusted by the anti-bias check results.

   **Narrow mode (≤3 ideators):** rank the raw ideator framings directly (no clustering needed).

   **Wide mode (>3 ideators):** rank the K cluster directions returned by `ideator-clusterer` (dispatched in Phase 2c-5; `CLUSTER_BLOCKS` holds the parsed result). Each cluster label represents one ranked direction; mention the underlying ideators that collapsed into it. If `CLUSTER_K = 0` (clusterer failure), fall back to presenting the N raw framings. Surface the cross-cluster consensus finding (if any) as a separate callout ("All directions agree that…").

   Send a `PushNotification` if notify.level is `approval_only` or `all` (see [docs/human/config.md](docs/human/config.md)).

   **HARD INVARIANT — Convergence guardrail:** The orchestrator MUST halt after producing this briefing and report to the user. It MUST NOT auto-decide, MUST NOT pick a framing on the user's behalf, and MUST NOT call any further tool. The next action comes only from the user's natural-language reply, interpreted in Phase 4.

---

## Phase 4 — Finalize

### HEAVY-mode branch (check FIRST — fires only when mode == HEAVY)

Read `$Z_HARNESS_PLAN_DIR/SCOPE-brainstorm.json`. If the file exists and `mode` is `"HEAVY"`, execute this branch and **skip the LIGHT/MEDIUM branch below entirely**.

#### Step 4H-1 — Build the (chunk × framing) matrix

Parse the unified BRAINSTORM.md that was written at the end of Phase 0's HEAVY fan-out (step 6 of the 0f HEAVY sub-section). The reconciler produces a strict chunk-major structure: each successful chunk is rendered under `## Chunk: <id>` heading (e.g. `## Chunk: C1`) and inside that section the per-ideator framings appear under `## Framing: <ideator>` sub-headings (e.g. `## Framing: claude`, `## Framing: codex`, `## Framing: gemini`) — same `## Framing:` pattern used by single-run BRAINSTORM.md per `/z-brainstorm` Phase 3. A chunk's framing scope ends at the next `## Chunk:` heading or EOF. Walk each `## Chunk: <id>` section in order. Skip chunks whose heading contains `— FAILED`. For each successful chunk, enumerate every `## Framing: <ideator>` sub-section actually present (skip any sub-section marked `<missing>` per ideator-failure convention). If a chunk has zero parseable `## Framing:` sub-sections, halt with `AskUserQuestion` ("reconciler emitted no framings for chunk <id> — repair manually / abandon / restart").

Collect a flat list of pairs in the form `(chunk_id, framing)`, e.g.:
```
[("C1","claude"), ("C1","codex"), ("C1","gemini"), ("C2","claude"), ("C2","codex"), ("C2","gemini"), ...]
```

Let `N_PAIRS = len(pairs)`.

#### Step 4H-2 — Present ranked pair briefing and end the turn

Do NOT use `AskUserQuestion` here. Do NOT call any further tool. Produce a ranked prose briefing of the (chunk, framing) pairs inline and stop — the orchestrator must wait for the user's natural-language reply.

**HEAVY mode ranks (chunk, framing) pairs.** Group by cluster of thematic similarity first (i.e. pairs from different chunks that share a framing approach), then rank within clusters by concreteness + lowest risk exposure. If the pairs naturally form no clusters, rank them flat.

**Ranked briefing format** (write this directly in your response):

> **Brainstorm complete — `<slug>` (HEAVY mode, <N_PAIRS> chunk×framing pairs)**
>
> Here are the **(chunk, framing) directions**, ranked by strength:
>
> **1. Chunk `<id>` / `<framing>` — <short label>**
> - **Pros:** <2-3 bullets>
> - **Cons:** <2-3 bullets>
>
> **2. Chunk `<id>` / `<framing>` — <short label>**
> - **Pros:** <2-3 bullets>
> - **Cons:** <2-3 bullets>
>
> *(repeat for each pair in ranked order)*
>
> **Consensus:** <one sentence on where the chunks/framings agree — call it a signal, not waste>
>
> **Divergence:** <one sentence on the genuine decision point across the pairs>
>
> **My recommendation:** Chunk `<id>` / `<framing>` — <one-sentence rationale>
>
> Which direction do you want to go? Name a chunk and framing to lock in, ask me to defend a choice, or restart/abandon.

The one-line summary for each pair is the first sentence of that chunk's ideator framing section in the unified BRAINSTORM.md. If the section is missing, use `<no summary available>`.

Send a `PushNotification` if notify.level is `approval_only` or `all` (see [docs/human/config.md](docs/human/config.md)).

**HARD INVARIANT — Convergence guardrail:** The orchestrator MUST halt after producing this briefing and report to the user. It MUST NOT auto-decide, MUST NOT pick a pair on the user's behalf, and MUST NOT call any further tool. The next action comes only from the user's natural-language reply, interpreted in Step 4H-3.

#### Step 4H-3 — Interpret the user's natural-language reply

This step is a **discussion loop** — there is no menu. Interpret the user's free-text reply from Step 4H-2 to determine intent. Present responses and end your turn — do NOT call any further tool until the user sends another reply.

**HARD INVARIANT — Ambiguity guardrail:** Write `chosen_pair` ONLY on an unambiguous lock-in signal. If the user's intent is ambiguous (could mean two pairs, or unclear which chunk), confirm conversationally before writing — never guess.

**Supported intents (natural language — no menu):**

**Ask a question** — the user wants to understand or compare a pair.
- Answer directly. Re-present the relevant pair(s) with your answer inline.
- Do NOT lock in unless the user explicitly requests it.
- End your turn.

**Challenge / narrow** — the user expresses doubt about a direction.
- Discuss the challenge; update the briefing view as appropriate.
- End your turn.

**Lock in** — the user clearly names a chunk and framing (e.g. "go with C2 / codex", "the gemini one for chunk 3", "use C1:claude").

**HARD INVARIANT:** Before writing, verify the signal is UNAMBIGUOUS — both the chunk and the framing must be identifiable. If either is ambiguous, ask for clarification conversationally; do NOT write.

On a clear lock-in:

1. Update the BRAINSTORM.md frontmatter atomically (tmp-file-then-rename). Build the full new frontmatter in memory, then write to a temp file in the same directory, then `os.replace()` over the original — never leave the file in an intermediate state where both `chosen_framing` and `chosen_pair` are present or where neither is present:
   - Remove the `chosen_framing:` field entirely.
   - Add `chosen_pair: {chunk_id: "<id>", framing: "<claude|codex|gemini>"}` (e.g. `chosen_pair: {chunk_id: "C1", framing: "codex"}`).
   - Confirm `status: complete`.
2. Append (for the first time) a `## User choice` body section:
   ```markdown
   ## User choice

   **Chosen pair:** chunk `<id>` / framing `<framing>`

   The framing text below seeds any downstream `/z-plan` invocation. Run `/z-plan` in the same working directory and it will auto-detect BRAINSTORM.md and read `chosen_pair` from the frontmatter.

   <verbatim text of the picked chunk's picked ideator framing block, copied from the `## Chunk: <id>` section of the unified BRAINSTORM.md>
   ```
3. Log the pick:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" heavy_pair_selected \
     "$(printf '{"chunk_id":"%s","framing":"%s"}' "<id>" "<framing>")"
   ```

**Restart** — the user wants to discard this run and re-brainstorm on a refined topic.

Follow the standard Restart path (see LIGHT/MEDIUM branch below) — archive BRAINSTORM.md with `chosen_framing: restart`, respond conversationally to ask for a refined topic, start a fresh RUN.

**Abandon** — the user wants to exit without finalizing.

Follow the standard Abandon path below. For HEAVY abandons, the frontmatter MUST match LIGHT/MEDIUM abandon shape exactly: set `status: abandoned` and `chosen_framing: abandoned`. Do NOT emit a `chosen_pair` key (it is only present on successful HEAVY completion). This keeps abandon detection uniform across modes.

#### Step 4H-4 — Fall through to "In all branches" below

After completing step 4H-3, skip the LIGHT/MEDIUM branch entirely and jump to "In all branches" at the end of this section. The `brainstorm_run_end` log event and push-notify are shared with the LIGHT/MEDIUM path.

For the `brainstorm_run_end` event, serialize `chosen_framing` as `"<chunk_id>:<framing>"` (e.g. `"C1:codex"`) for HEAVY picks, or `"restart"` / `"abandoned"` for those exits.

---

### LIGHT/MEDIUM branch (fires when mode is NOT HEAVY, or SCOPE-brainstorm.json is absent)

This branch is a **discussion loop**. There is no menu; interpret the user's free-text reply from Phase 3 to determine intent. Present responses and end your turn — do NOT call any further tool until the user sends another reply.

**HARD INVARIANT — Ambiguity guardrail (m5):** Write `chosen_framing` and the `## User choice` block ONLY on an unambiguous lock-in signal. If the user's intent is ambiguous, confirm conversationally before writing — never guess. A silent auto-write loses user intent and is the riskiest new behavior in this command.

#### Supported intents (natural language — no menu)

**Ask a question** — the user wants to understand or compare the framings.
- Answer the question directly. Re-present the relevant framing(s) with your answer inline.
- Do NOT re-spin or lock in unless the user explicitly requests it.
- End your turn.

**Challenge / narrow** — the user expresses doubt about a direction or wants to cut scope.
- Discuss the challenge; update the briefing view as appropriate.
- If the challenge is strong enough to suggest the current framings don't cover the right space, offer a re-spin (see re-spin machinery). Only initiate if the user agrees.
- End your turn.

**Combine X+Y** — the user wants a hybrid of two directions.
- Draft a synthesized framing inline (the five-section schema: Framing / Core hypothesis / Risks / Plan implications / What would change my mind). Label it clearly ("Synthesized: <X> + <Y>").
- Show it and ask the user to confirm before treating it as the chosen framing.
- End your turn. Do NOT write `chosen_framing` yet.

**Re-spin** — the user wants divergent options (see re-spin machinery, T007).
- Acknowledge the re-spin request and note "re-spin 1/3, ~X tokens" before dispatching.
- After the re-spin returns, produce an updated ranked briefing incorporating the new framings and end your turn.

**Lock in** — the user clearly selects a framing (e.g. "go with Codex", "I like option 2", "use the synthesized one", "let's do X").

**HARD INVARIANT:** Before writing, verify the signal is UNAMBIGUOUS. If it could mean two things, ask for clarification. Only on a clear lock-in:

1. Update `chosen_framing:` in the BRAINSTORM.md frontmatter from `pending` to the locked-in value:
   - Single ideator pick → `claude` | `codex` | `gemini`
   - Synthesized / hybrid → `synthesized`
2. Append (for the first time) a `## User choice` body section:
   ```markdown
   ## User choice

   **Chosen framing:** <framing label>
   <!-- For a single ideator pick: framing label is the ideator id (e.g. "claude", "codex", "gemini") -->
   <!-- For synthesized: framing label is "synthesized" or a descriptive label (e.g. "Synthesized: Codex framing + Claude risk model") -->

   <For a single ideator pick: reproduce the ideator's framing block verbatim (all five sections) so /z-plan can find it without re-parsing>
   <For synthesized: write the FULL co-authored hybrid text — the merged framing born from the discussion (e.g. "Codex's framing + Claude's risk model"). This is the text the orchestrator and user co-authored conversationally, NOT a verbatim copy of any single vendor's framing block. Include all five sections (Framing / Core hypothesis / Risks / Plan implications / What would change my mind) so /z-plan has a complete seed>

   <Any free-text refinement the user added during the discussion>
   ```
3. Confirm `status: complete` in the frontmatter.
4. Log the pick:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" framing_locked \
     "$(python3 -c 'import json,sys; print(json.dumps({"chosen_framing":sys.argv[1]}))' "<framing>")"
   ```

**Restart** — the user wants to discard this run and re-brainstorm on a refined topic.

1. Archive the just-written BRAINSTORM.md to `$Z_HARNESS_PLAN_DIR/archive/$RUN/BRAINSTORM.md.previous-<N>` (next free integer). Before archiving, update the archived copy's frontmatter to `status: complete`, `chosen_framing: restart` so the historical record is spec-valid.
2. Ask the user for the refined topic conversationally (e.g. "What topic should I brainstorm instead?") — do NOT use `AskUserQuestion` here; respond in prose and end your turn to wait for their reply.
3. After the user replies with the refined topic: start a fresh RUN — regenerate `RUN`, re-mkdir, re-emit `brainstorm_run_start`, and loop back to Phase 1 with the refined topic.

**Abandon** — the user wants to exit without finalizing.

1. Set the frontmatter `status: abandoned` and `chosen_framing: abandoned`. Leave the file in place (so a future re-run knows there was a prior attempt).
2. Skip the push-notify "next step" recommendation; emit a simpler "abandoned" notification.

**Ambiguous reply** — the user's reply doesn't map cleanly to any of the above intents.
- Ask a targeted clarifying question (one sentence). End your turn. Do NOT write anything to BRAINSTORM.md.

---

### Re-spin machinery

This section is a **shared helper** used by the Phase 4 discussion loop (LIGHT/MEDIUM branch) and by T011's wide-mode overflow. Both callers reference "re-spin machinery" — implement once here, invoke by name from both sites.

#### Inputs

Before executing a re-spin wave, the caller must have determined:

- `RESPIN_DIRECTION` — the narrowed direction string from the user (e.g. "focus on the security axis" or the user's challenge text). If the caller is the discussion loop, derive this from the user's challenge or re-spin request. If the caller is wide-mode overflow, this is the divergence axis not yet covered by prior waves.
- `RESPIN_WAVE` — the wave number being dispatched (1, 2, or 3). Track this in the run context. Wave 1 is the first re-spin (not the original Phase 2 dispatch).
- `RESPIN_PRIOR_FRAMINGS` — the concatenated framing blocks (five-section schema) from all ideators dispatched so far (Phase 2 wave + any prior re-spin waves). Extract these from the BRAINSTORM.md body — every `## Framing` subsection under every wave header.

#### Cap enforcement

**Hard cap: 3 re-spin waves maximum.** Before dispatching:

```bash
if [[ "${RESPIN_WAVE:-1}" -gt 3 ]]; then
  # Inform the user that the re-spin cap has been reached.
  # Do NOT dispatch any ideators. Return to the discussion loop.
  echo "Re-spin cap reached (3/3). No further re-spin waves are available for this brainstorm run." >&2
  exit 0
fi
```

If the cap is reached, tell the user conversationally: "We've reached the re-spin limit (3 waves). If the current options still don't fit, consider a Restart to brainstorm a refined topic from scratch." Do not dispatch any ideators. End your turn.

#### Subset selection

A re-spin dispatches **2 of the 3** vendor arms (not all 3), chosen to maximise diversity relative to what already returned divergent framings. Default subset: `general-purpose` (Claude) + one consultant arm chosen round-robin:

- Wave 1 → Claude + Codex (`general-purpose` + `consultant-secondary`)
- Wave 2 → Claude + Gemini (`general-purpose` + `consultant-primary`)
- Wave 3 → Codex + Gemini (`consultant-secondary` + `consultant-primary`)

Rationale: keeping Claude in waves 1 and 2 anchors the synthesis comparison; wave 3 drops Claude to force a fully non-Claude axis. The caller (discussion loop or wide mode) does NOT need to pick the subset — the wave number determines it deterministically.

#### Anti-seed prompt construction

Build the anti-seed payload once before dispatching both ideators. It must contain:

1. The `narrowed_direction` from `RESPIN_DIRECTION`.
2. The full text of `RESPIN_PRIOR_FRAMINGS` (all existing framing blocks), labelled clearly.
3. The divergence instruction (verbatim, do not paraphrase):

   > "Here are the existing framings from this brainstorm run. Produce something that **diverges from all of them** — attack a **different axis** (different core hypothesis, different problem decomposition, different target user, or different solution lever). Do NOT restate, synthesize, or incrementally improve an existing framing. The goal is genuine divergence."

Full anti-seed prompt template for each re-spin ideator:

```
<PERSONA_PREFIX (same resolution as Phase 2 — draw a fresh random persona for this ideator slot for this wave)>
MODE: brainstorm

Topic: <topic>

Narrowed direction from the user: <RESPIN_DIRECTION>

Here are the existing framings from this brainstorm run:

<RESPIN_PRIOR_FRAMINGS>

Produce something that diverges from all of them — attack a different axis (different core hypothesis, different problem decomposition, different target user, or different solution lever). Do NOT restate, synthesize, or incrementally improve an existing framing. The goal is genuine divergence.

<IDEATOR_SCHEMA (same five-section schema as Phase 2)>
```

#### Cost estimate and user notification

Before dispatching the ideators, emit a one-line cost note to the user (inline in your response, not a log event):

> "Re-spin `<RESPIN_WAVE>`/3, ~`<N_IDEATORS × estimated_tokens>` tokens — dispatching `<N_IDEATORS>` ideators on a divergent axis."

Use `N_IDEATORS = 2`. Token estimate: ~1,500 tokens per ideator call (input + output combined) is a reasonable heuristic for brainstorm-scale prompts; use `~3,000 tokens total` for the two-ideator subset. If the actual payload is materially larger (e.g. RESPIN_PRIOR_FRAMINGS is very long), adjust the estimate up — the goal is a directionally correct number, not precision.

#### Dispatch

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip the re-spin ideator Agent() calls.
     Re-spin cannot complete without subagent support. -->
```

Dispatch the subset pair in **parallel** (same as Phase 2 parallel dispatch):

**Wave 1 and Wave 2 (Claude + one consultant):**

```
Agent(
  subagent_type="general-purpose",
  model="sonnet",
  description="Claude re-spin ideator wave <RESPIN_WAVE> for <slug>",
  prompt="<anti-seed prompt for Claude, per template above>"
)
Agent(
  subagent_type="<consultant-secondary|consultant-primary per wave>",
  description="<Codex|Gemini> re-spin ideator wave <RESPIN_WAVE> for <slug>",
  prompt="<anti-seed prompt for that consultant, per template above>"
)
```

**Wave 3 (Codex + Gemini, no Claude):**

```
Agent(
  subagent_type="consultant-secondary",
  description="Codex re-spin ideator wave 3 for <slug>",
  prompt="<anti-seed prompt for Codex>"
)
Agent(
  subagent_type="consultant-primary",
  description="Gemini re-spin ideator wave 3 for <slug>",
  prompt="<anti-seed prompt for Gemini>"
)
```

Apply the same persona resolution as Phase 2 (draw a fresh random persona per ideator slot per wave, if `brainstorm.personas` is ON; skip if OFF or underflow). The anti-seed instruction is in addition to — not instead of — the persona prefix.

#### Failure policy

Apply the same failure policy as Phase 2 ideators:

- **1/2 fail** → proceed with the surviving one. Record the failed member as `<id>:failed` in the wave header comment (see BRAINSTORM.md append below).
- **2/2 fail** → inform the user conversationally ("Both re-spin ideators failed — re-spin wave `<N>` produced no new framings"). Do NOT decrement `RESPIN_WAVE` (the wave still consumed a slot toward the cap). Return to the discussion loop without appending to BRAINSTORM.md for this wave.

Log every individual failure as `ideator_failed` with `{vendor, reason, wave: RESPIN_WAVE}`.

#### Telemetry

Emit a `respin_wave` event immediately after the ideators return (regardless of failure):

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" respin_wave \
  "$(python3 -c 'import json,sys; print(json.dumps({"wave":int(sys.argv[1]),"n_ideators":int(sys.argv[2]),"failed":int(sys.argv[3])}))' \
     "$RESPIN_WAVE" "2" "<0 or number of failed ideators>")"
```

#### BRAINSTORM.md append

On success (at least 1 surviving ideator), append to `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md` under a new wave header. Do NOT rewrite the file — append only:

```markdown

## Re-spin wave <RESPIN_WAVE>

<!-- re-spin direction: <RESPIN_DIRECTION> -->
<!-- ideators: <list of dispatched ideators, e.g. claude, codex>; failed: <list or "none"> -->

### Framing — <ideator-id> (re-spin wave <RESPIN_WAVE>)

<five-section block from ideator, verbatim>

### Framing — <ideator-id> (re-spin wave <RESPIN_WAVE>)

<five-section block from second ideator, if surviving>
```

The wave header (`## Re-spin wave N`) makes the file self-describing and allows the discussion loop to locate all prior framings by scanning from the top. The `<!-- re-spin direction -->` comment preserves the narrowing context for any future resumption.

#### Post-dispatch: return to the caller

After appending to BRAINSTORM.md and emitting the `respin_wave` event:

- **If called from the Phase 4 discussion loop:** produce an updated ranked briefing that incorporates the new wave's framings alongside the original Phase 2 framings, then end your turn. The ranked briefing follows the same format as the Phase 3 briefing (pros/cons, consensus vs divergence, recommendation). Do NOT auto-lock-in a framing — wait for the user's next reply.
- **If called from wide-mode overflow (T011):** return the new framings to the caller for clustering by `ideator-clusterer`; do not produce a ranked briefing here (the wide-mode path handles presentation).

The RESPIN_WAVE counter must be incremented by the caller after a successful dispatch (including partial-success single-survivor waves). A fully-failed wave (2/2 fail) does NOT increment the counter toward the cap (the slot is not consumed).

---

### In all branches

**Run Brief finalize (registry Phase 4).** Set outcome/next from the user's Phase 4 pick, pre-seed approach from `BRAINSTORM.md` when present, then include the shared fragment before `brainstorm_run_end`. Chat and push text are rendered from `run-brief.json` only — do not author independent completion prose.

```bash
CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="$Z_HARNESS_PLAN_DIR/BRAINSTORM.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS=""
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"

RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"

# BS_STATUS: complete | abandoned; BS_CHOSEN_FRAMING: ideator id, "<chunk>:<framing>", restart, or abandoned
if [[ "${BS_STATUS:-complete}" == "abandoned" ]]; then
  _RB_OUTCOME="Brainstorm abandoned"
  _RB_NEXT_LABEL="Re-run /z-brainstorm or proceed without a framing"
  _RB_NEXT_CMD="/z-brainstorm"
elif [[ "${BS_CHOSEN_FRAMING:-}" == *:* ]]; then
  _RB_OUTCOME="Brainstorm complete (pair: ${BS_CHOSEN_FRAMING})"
  _RB_NEXT_LABEL="Start planning via /z-plan (auto-detects BRAINSTORM.md)"
  _RB_NEXT_CMD="/z-plan"
else
  _RB_OUTCOME="Brainstorm complete (framing: ${BS_CHOSEN_FRAMING:-unknown})"
  _RB_NEXT_LABEL="Start planning via /z-plan (auto-detects BRAINSTORM.md)"
  _RB_NEXT_CMD="/z-plan"
fi

bash "$RB_SH" set-section --run "$RUN" --section outcome --value "$_RB_OUTCOME"
bash "$RB_SH" set-section --run "$RUN" --section next --json /dev/stdin <<JSON
{"label": "${_RB_NEXT_LABEL}", "command": "${_RB_NEXT_CMD}"}
JSON

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
      "- Parallel vendor-diverse ideation (Claude + Codex + Gemini)" \
      "- Mandatory anti-bias reconciliation" \
      "- User-selected framing in ## User choice seeds downstream /z-plan" \
      > "$_RB_SEED"
    bash "$RB_SH" set-section --run "$RUN" --section approach --file "$_RB_SEED" || true
  fi
fi
bash "$RB_SH" set-section --run "$RUN" --section status --value "complete"
```

<!-- include: _fragments/run-brief-finalize.md -->

Log `brainstorm_run_end`:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" brainstorm_run_end \
  "$(printf '{"command":"z-brainstorm","status":"%s","chosen_framing":"%s","ideators_failed":%d}' \
     "<complete|abandoned>" "<framing-or-empty>" "<N>")"
```

For the `brainstorm_run_end` event, serialize `chosen_framing` as `"<chunk_id>:<framing>"` (e.g. `"C1:codex"`) for HEAVY picks, or `"restart"` / `"abandoned"` for those exits.

---

## Run Brief — halt finalize

Before exit on any halt after `run-brief.sh init` when `BRAINSTORM.md` is missing or the run aborts early (e.g. 3/3 ideator failure, 2/3 abandon). Substitute `<reason>` in the outcome line. Fragment auto-downgrades to **lite** when the artifact file is absent.

```bash
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="${Z_HARNESS_PLAN_DIR}/BRAINSTORM.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS=""
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
bash "$RB_SH" set-section --run "$RUN" --section next --json /dev/stdin <<'JSON'
{"label": "Retry /z-brainstorm or diagnose ideator failures", "command": "/z-brainstorm"}
JSON
```

<!-- include: _fragments/run-brief-finalize.md -->

---

## Telemetry reference

| Event kind | When / meaning | Required fields |
|---|---|---|
| `brainstorm_run_start` | Brainstorm run begins | version fields, `topic`, `command` |
| `brainstorm_run_end` | Brainstorm run completes | `command`, `status`, `chosen_framing`, `ideators_failed` |
| `ideator_failed` | One of the three ideators failed | `vendor`, `reason` |
| `total_ideator_failure` | All three ideators failed; hard halt | — |
| `scope_probe_start` | Scope-probe Agent dispatched | `host_command`, `axis_taxonomy` |
| `scope_probe_classified` | Scope-probe returned a classification | `host_command`, `mode`, `axis`, `confidence`, `chunks_count` |
| `scope_probe_malformed` | Scope-probe return failed to parse | `host_command`, `raw_response_len` |
| `scope_probe_low_confidence` | Scope-probe returned `CONFIDENCE: low`; downgraded to MEDIUM | — |
| `scope_probe_refused` | Scope-probe returned `STATUS: refused`; MEDIUM fallback | `host_command` |
| `scope_probe_bad_input` | Scope-probe returned `STATUS: bad_input`; MEDIUM fallback | `host_command` |
| `scope_probe_archive_write_failed` | Archive write for SCOPE.json failed | — |
| `scope_probe_skipped_fast_path` | Single-file target auto-classified LIGHT, scope-probe Agent skipped | `command` (`z-brainstorm`), `target`, `arg_len` |
| `scope_fanout_dispatched` | HEAVY mode: N sub-flows launched | `host_command`, `axis`, `chunks_count` |
| `scope_fanout_reconciled` | HEAVY mode: reconciler finished | `host_command`, `axis`, `chunks_total`, `chunks_succeeded`, `reconciler_ok` |
| `heavy_pair_selected` | HEAVY mode: user chose a (chunk, framing) pair | `chunk_id`, `framing` |
| `framing_locked` | LIGHT/MEDIUM branch: user unambiguously locked in a framing (conversational) | `chosen_framing` |
| `doc_drift` | doc-fetcher returned a DRIFT WARNING for a concept | `concept`, `claim`, `reality`, `file` |
| `sharpen_gate` | Phase 0 sharpen-vs-skip decision | `decision` (`sharpen`\|`skip`), `reason`, `grill_md_existed` |
| `count_parsed` | Phase 0 ideator count extracted from NL invocation | `wide_n`, `default_used` |
| `wide_suppressed_heavy` | N>3 wide request suppressed HEAVY chunking (D2) | `requested_n`, `scope_mode` |
| `wide_dispatch` | Wide mode confirmed by user; all waves + clusterer dispatched | `wide_n`, `waves`, `overflow_model` |
| `wide_overflow_model_warn` | `cheap-mixed` resolved but no `--model` path verified; fell back to haiku | `reason`, `config_value` |

---

## Operating principles

- **Cheap and parallel.** Three ideators in one message, no per-ideator round-trips.
- **Identical scaffolding for all three.** No read-by-reference asymmetry.
- **Anti-bias is mandatory.** Every Claude-favoring pick needs explicit justification.
- **Failures degrade gracefully** — 1/3 proceeds, 2/3 asks, 3/3 halts.
- **Restart is cheap.** Archive and loop, don't try to patch.
- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
- **Log everything** via `scripts/log-event.sh`.
- **Brainstorm tail never auto-decides (m5 — load-bearing).** The orchestrator MUST halt after the Phase 3 ranked briefing and wait for the user's natural-language reply. It MUST NOT auto-pick a framing. It writes `chosen_framing` and the `## User choice` block ONLY on an unambiguous lock-in signal from the user. An ambiguous reply triggers a clarifying question, never a write. A silent auto-write would lose the user's intent — this is the riskiest behavior in this command.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Phase 0 sharpen-gate optional Haiku Agent() (ambiguous topics only); Phase 0 scope-probe Agent(); HEAVY sub-flow and reconciler Agent() calls; Phase 1a doc-fetcher Agent(); Phase 1b optional Explore Agent(); Phase 2 three ideator Agent() calls; Phase 2c overflow ideator Agent() calls (wide mode only, WIDE_N > 3); Phase 2c-5 ideator-clusterer Agent() (wide mode only) |
| `ask_user` | yes | Empty topic gate (finite); Setup slug confirmation (finite); Setup existing BRAINSTORM.md overwrite (finite); Phase 2 2/3 ideator failure gate (finite); Phase 4 HEAVY "no framings" halt (finite). **Conversational (no ask_user):** Phase 3 framing-selection briefing; Phase 4 HEAVY chunk×framing matrix (T009); Phase 4 LIGHT/MEDIUM discussion loop including restart refined-topic |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
