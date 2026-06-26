---
name: z-explore
disable-model-invocation: false
description: depth-scaled codebase terrain explorer; quick scout through deep MAP.md equivalent for /z-map replacement
argument-hint: "<question> [--depth=quick|standard|deep] [--repo] [--slug=<kebab>] [--surface=auto|off|force]"
runtime: c1
driver_features_required:
  - subagent
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are running the **z-harness `/z-explore`** pipeline — a depth-scaled terrain discovery command that replaces `/z-map` for quick scouts through deep MAP.md equivalents.

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
- `deep`: up to 3 Haiku/Sonnet Explores, full research-draft + bundled cross-LLM critique + MAP.md. Full z-map equivalent.

**Known v1 limitation:** `Agent()` does not expose a per-call wall-clock timeout. Subagents that hang block the run. User escape: ctrl-c.

## Setup

1. **Parse `--depth=` flag** from `$ARGUMENTS`. If present, strip it and set `EXPLORE_DEPTH=<quick|standard|deep>`. Default: `quick`. Valid values only — if unrecognized, error and ask user. Initialize `CITATION_COUNT=0` and `GAP_COUNT=0` for telemetry tracking during synthesis (see Phase 4).

2. **Parse `--slug=<value>` flag** from `$ARGUMENTS`. If present, strip the entire `--slug=<value>` token from the arguments — the remainder is the exploration question, and the explicit slug overrides auto-derivation. The stripped `--slug=` token MUST NOT appear in any prompt to subagents and MUST NOT be included in the canonical text fed into `input_hash` (use only the cleaned exploration question + any non-`--slug` flags). Store the original normalized invocation (question + supported flags) separately for the final `command:` frontmatter.

   **Derive a research slug** (only if `--slug=` was not provided): from the cleaned question, short kebab-case, 2-4 words (e.g. "how does the retry logic work?" → `retry-logic`). Run `bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" all_plan_slugs` to check for existing slug names. Slug-collision handling is deferred to **Phase 1** (after the cost gate, for deep mode) or handled inline for quick/standard.

   If `--slug=` was explicitly provided, skip auto-derivation.

3. **Export** `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")` for all subsequent shell calls and subagents.

4. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`

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

<!-- ROUTE_CHECK_START -->
## Route check

Advisory-only routing. Run this route check before Phase 1. Use only already-known signals from the question, slug/artifact collision check, and docs availability.

Never auto-dispatch. Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md` and present the user with recommended next steps via `AskUserQuestion`:

- `z-explore --depth=deep` (replaces z-map) — full MAP.md with cross-LLM critique when deep terrain certainty is required.
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

Depth-dependent cost handling:

**`quick` mode:** No cost gate. Proceed directly to Phase 2.

**`standard` mode:** Simple cost note — log a `cost_note` event stating estimated ~500k tokens, then proceed without user prompt.

**`deep` mode:** Full cost gate, same as `/z-map` Phase 0. Present the cost up front via `AskUserQuestion` with three options:

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

For **deep** mode: after the cost gate, run Phase 0.5 slug + artifact collision handling (same as `/z-map` Phase 0.5 — check existing `$Z_HARNESS_PLAN_DIR/` dirs and `MAP.md`, prompt user for archive-and-start-fresh / continue / abort).

Checkpoint: `phase1-cost-gate.md`.

## Phase 2 — Doc grounding

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

Track `EXPLORES_DISPATCHED` and `EXPLORES_SUCCEEDED` per z-map conventions.

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

Same as `/z-map` Phase 2. Dispatch up to `EXPLORE_BUDGET` (3 or 1) parallel `Explore` subagents. Use Haiku for locating tasks, Sonnet for interpretation tasks:

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
- /z-map <topic> — full MAP.md with cross-LLM critique
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

1. **Write research-draft.md** — same as `/z-map` Phase 3:
   ```markdown
   ## Findings
   ## Constraints discovered
   ## Open questions
   ## No-recommendation
   ```
   With citation enforcement, demotion rule, and the invariant `## No-recommendation` section.

2. **Bundled consultant critique** — same as `/z-map` Phase 4. Spawn **both** consultants in parallel:
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
   Per-consultant failure policy (retry-once, then log failed), aggregate decision logic — same as `/z-map` Phase 4.

3. **Revise** — update research-draft.md with critique, add `## Cross-LLM review notes` section.

4. **Write MAP.md** — same as `/z-map` Phase 6 output format:
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

Checkpoint: `phase4-synthesis.md` (or `phase4-draft.md` → `phase4-critiques.md` → `phase4-revised.md` for deep mode).

## Phase 5 — Finalize

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

Send a `PushNotification` if policy ≠ `off` with a next-step recommendation:

```
Explore complete. Depth: <depth>.

Recommended next step:
  /z-map <topic>   — full MAP.md with cross-LLM critique
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
