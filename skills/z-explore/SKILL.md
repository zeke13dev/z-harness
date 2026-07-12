---
name: z-explore
description: depth-scaled codebase terrain explorer; quick scout through deep MAP.md terrain synthesis
argument-hint: "<question> [--depth=quick|standard|deep] [--slug=<kebab>]"
audience: user
driver_features_required: [subagent, ask_user]
---

You are running the **z-harness `/z-explore`** pipeline — a depth-scaled terrain discovery command from quick scouts through deep MAP.md synthesis.

Question (from `$ARGUMENTS`):

$ARGUMENTS

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the question
     "What question should I explore?" to the user via their native channel and
     accept a text reply. Silent omission is forbidden. -->
**If the question above is empty or whitespace**, use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask "What question should I explore?". Wait for their reply and treat it as the question. Pre-preflight: a plain exit here is fine if none is given — nothing is registered yet.

Strict, multi-phase. Do not skip phases. `/z-explore` produces a terrain note only — it maps terrain, it does not pick an approach. Implementation and approach-selection happen later via `/z-brainstorm` or `/z-plan`.

**Depth modes** (parsed from `--depth=` argument):
- `quick` (default): 1-2 Haiku Explores, inline findings. Low cost, fast turnaround.
- `standard`: up to 3 Haiku Explores, persisted EXPLORE.md + surface-map.json. Moderate cost.
- `deep`: up to 3 Haiku/Sonnet Explores, full research-draft + bundled cross-LLM critique + MAP.md. Full terrain synthesis.

**Known v1 limitation:** `Agent()` does not expose a per-call wall-clock timeout. Subagents that hang block the run. User escape: ctrl-c.

## Setup

1. **Parse `--depth=` flag** from `$ARGUMENTS`. If present, strip it and set `EXPLORE_DEPTH=<quick|standard|deep>`. Default: `quick`. Valid values only — if unrecognized, error and ask user (pre-preflight; plain exit). Initialize `CITATION_COUNT=0` and `GAP_COUNT=0` for telemetry tracking during synthesis (see Phase 4).

2. **Parse `--slug=<value>`, `--resume-phase=<seam_id>`, and `--resume-run=<run-id>` flags** — one pass, reused by the resume gate below (never re-parsed). Strip each entire token from the cleaned exploration question; the stripped resume tokens MUST NOT appear in prompts, slug derivation, or `input_hash`. Store as `RESUME_PHASE` / `RESUME_RUN`.

   **Derive a research slug** (only if `--slug=` was not provided): from the cleaned question, short kebab-case, 2-4 words. Run `bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" all_plan_slugs` to check for existing slug names. Slug-collision handling is deferred to **Phase 1** (after the cost gate, for deep mode) or handled inline for quick/standard. This derivation MUST still run on a resumed invocation — the resume command (below) carries the slug as its bare leading token, so re-deriving from the cleaned question reproduces the same slug; `Z_HARNESS_SLUG` is required by the preflight call in step 3 regardless of resume state.

3. **Preflight ceremony (single call, read-only).** `/z-explore` never edits the codebase — only its own terrain artifacts under `$Z_HARNESS_PLAN_DIR/` — so it runs the lifecycle **minus the claim** (SKILL-STYLE.md §2):
   ```bash
   PREFLIGHT_OUT="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-preflight.sh" \
     --command /z-explore --slug "$Z_HARNESS_SLUG" --no-claim \
     --intent "<cleaned question — max 240 chars; not the command name alone>")"
   PREFLIGHT_RC=$?
   [ "$PREFLIGHT_RC" -eq 0 ] && eval "$PREFLIGHT_OUT"
   ```
   `--no-claim` skips the claim step entirely (script header) — `plan-claim.sh acquire` is never invoked, so contention/corrupt-lock exits (10/11) cannot occur here. A nonzero `PREFLIGHT_RC` on a `--no-claim` call means a genuine setup failure (bad invocation or path resolution); surface the stderr diagnostic and exit — nothing was ever created or registered. On success, `RUN`, `Z_HARNESS_PLAN_DIR`, `CURRENT_ARCHIVE_DIR`, `Z_HARNESS_SESSION_ID`, and `KERNEL_PATH` are exported (script header is the source of truth).

4. **Resume-run override.** If `RESUME_RUN` is set, this invocation is continuing a prior deep-mode run rather than starting a fresh one: `RUN="$RESUME_RUN"; CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`. The preflight call above still minted a fresh throwaway run id/archive dir as a side effect (registration only, harmless); this override redirects all subsequent artifact paths to the resumed run. `mkdir -p "$CURRENT_ARCHIVE_DIR/transcripts"` defensively.

5. Log the explore run start (domain-specific fields the generic wrapper `run_start` event doesn't carry):
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["question"] = sys.argv[2]; v["depth"] = sys.argv[3]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<cleaned question>" "$EXPLORE_DEPTH")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" explore_run_start "$START_PAYLOAD"
   ```

6. **Parent attribution (sub-command contract).** If `$Z_HARNESS_PARENT_RUN_ID` is set (this run was dispatched by a meta-orchestrator like `/z-research`), include `parent_run_id` and `parent_command` fields in every subsequent `log-event.sh` payload this skill emits directly (the wrapper's own `run_start`/`run_end` do not carry these — a known wrapper gap, not fixed here):
   ```bash
   bash log-event.sh "$RUN" some_event "$(python3 -c 'import json,os,sys; p=json.loads(sys.argv[1]);
   pid=os.environ.get("Z_HARNESS_PARENT_RUN_ID"); pcmd=os.environ.get("Z_HARNESS_PARENT_COMMAND");
   if pid: p["parent_run_id"]=pid;
   if pcmd: p["parent_command"]=pcmd;
   print(json.dumps(p))' "$ORIG_PAYLOAD")"
   ```
   If env vars absent, emit events as today (no attribution fields).

7. Notification policy: see [docs/human/config.md](docs/human/config.md) (notify.level key).

8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 2 will dispatch `doc-fetcher` (Haiku).

**Setup does NOT mutate `$Z_HARNESS_PLAN_DIR/MAP.md` or any sibling artifact.**

**All paths in subsequent phases live under `$Z_HARNESS_PLAN_DIR/`:**
- `$Z_HARNESS_PLAN_DIR/MAP.md`
- `$Z_HARNESS_PLAN_DIR/EXPLORE.md`
- `$Z_HARNESS_PLAN_DIR/surface-map.json`
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/...`

### Halt funnel

Every controlled non-complete exit after preflight funnels through this one function — never a bare `exit` (SKILL-STYLE.md §2, single exception: a checkpoint-seam PAUSE, which is not an exit):

```bash
explore_halt() {
  local reason="$1"
  local rb="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
  bash "$rb" set-section --run "$RUN" --section outcome --value "Halted: ${reason}"
  bash "$rb" set-section --run "$RUN" --section next --json /dev/stdin <<'JSON'
{"label": "Review the halt reason and re-run /z-explore", "command": null}
JSON
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
    --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-explore --status aborted
  exit 1
}
```

`z-teardown.sh` finalizes the brief (auto-synthesizing `approach` from the `Halted: ...` outcome when no artifact exists — `run-brief.sh`'s own downgrade rule), releases the never-held claim (best-effort no-op), deregisters, and emits `run_end`.

## Shared context checkpoint hook/check contract for deep terrain mode

`/z-explore --depth=deep` owns the active terrain checkpoint seams. It MUST NOT keep workflow-local acknowledgement files or direct `handoff.json` writers. Do not write `handoff.json` directly.

Every durable-boundary checkpoint seam is one call to `scripts/checkpoint-seam.sh` (SKILL-STYLE.md §2), wrapped here since deep mode has five call sites:

```bash
explore_checkpoint_seam() {
  local seam_id="$1" artifact="$2" next_step="$3"; shift 3 || true
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/checkpoint-seam.sh" \
    "$seam_id" "$artifact" "/z-explore --depth=deep $Z_HARNESS_SLUG --resume-phase=$seam_id --resume-run=$RUN" \
    --producer z-explore --next-step "$next_step" "$@"
  local rc=$?
  case "$rc" in
    0) return 0 ;;  # below threshold, or already fast-forwarded — continue
    1) exit 0 ;;     # new checkpoint written — pause here, not an error; next invocation resumes
    2) explore_halt "context pressure estimate failed in strict mode at $seam_id" ;;
  esac
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

Skipped candidate seams: no check before a deep-mode durable artifact exists; no check while Explore or consultant workers are in flight; no check after terminal halt because the halt funnel owns that state.

### Deep-mode resume-phase gate

If `RESUME_PHASE` (Setup step 2) is set, validate the corresponding `$Z_HARNESS_PLAN_DIR/.clear-checkpoint-<seam_id>.json` before route/cost/doc/explore dispatch, recompute the fast-forward guard from the current durable artifacts, and jump directly to the recorded next phase. Never rerun earlier Explore or consultant work silently on a checkpoint resume.

```bash
if [ -n "$RESUME_PHASE" ]; then
  case "$RESUME_PHASE" in
    map-phase4-pre-critique) RESUME_TARGET="critique"; REQUIRED_ARTIFACT="$Z_HARNESS_PLAN_DIR/archive/$RUN/research-draft.md" ;;
    map-phase4-post-critique) RESUME_TARGET="revision"; REQUIRED_ARTIFACT="$Z_HARNESS_PLAN_DIR/archive/$RUN/critique-manifest.json" ;;
    map-phase4-pre-map-write) RESUME_TARGET="map-write"; REQUIRED_ARTIFACT="$Z_HARNESS_PLAN_DIR/archive/$RUN/research-draft.md" ;;
    map-phase5-pre-final-review) RESUME_TARGET="final-review"; REQUIRED_ARTIFACT="$Z_HARNESS_PLAN_DIR/MAP.md" ;;
    map-phase5-pre-user-report) RESUME_TARGET="user-report"; REQUIRED_ARTIFACT="$Z_HARNESS_PLAN_DIR/MAP.md" ;;
    *) explore_halt "unknown /z-explore resume phase: $RESUME_PHASE" ;;
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
  python3 - "$STATE_FILE" "$RESUME_PHASE" "$REQUIRED_ARTIFACT" "$CURRENT_GUARD" <<'PYEOF' || explore_halt "stale or invalid /z-explore checkpoint state for $RESUME_PHASE"
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
- **Abandon** — exit cleanly, write nothing beyond what's already registered.

Log the user's pick:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cost_gate_decision \
  "$(printf '{"choice":"%s"}' "<proceed|reduce|abandon>")"
```

If `abandon`: `explore_halt "user abandoned deep-mode cost gate"`. If `reduce`: set `EXPLORE_BUDGET=1`. Otherwise `EXPLORE_BUDGET=3`.

For **deep** mode: after the cost gate, run Phase 0.5 slug + artifact collision handling (check existing `$Z_HARNESS_PLAN_DIR/` dirs and `MAP.md`, prompt user for archive-and-start-fresh / continue / abort).

## Phase 2 — Doc grounding

If `Z_EXPLORE_RESUME_TARGET` is set, skip Phase 2.

If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:

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
   explore_checkpoint_seam map-phase4-pre-critique \
     "$Z_HARNESS_PLAN_DIR/archive/$RUN/research-draft.md" \
     "continue at bundled consultant critique dispatch" \
     --hash "$Z_HARNESS_PLAN_DIR/MAP.md"
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
   Per-consultant failure policy: retry once, then log failed. Require at least one successful critique before revising; if both fail, use the both-consultants-failed `ask_user` gate before proceeding — **abort** funnels through `explore_halt "both consultant critiques failed"`.

   After critique transcripts are archived, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/critique-manifest.json`, then checkpoint before revised-draft synthesis:
   ```bash
   explore_checkpoint_seam map-phase4-post-critique \
     "$Z_HARNESS_PLAN_DIR/archive/$RUN/critique-manifest.json" \
     "continue at research-draft revision" \
     --hash "$Z_HARNESS_PLAN_DIR/MAP.md"
   ```

3. **Revise** — update research-draft.md with critique, add `## Cross-LLM review notes` section.

   After the revised draft is durable, checkpoint before final MAP.md synthesis/write:
   ```bash
   explore_checkpoint_seam map-phase4-pre-map-write \
     "$Z_HARNESS_PLAN_DIR/archive/$RUN/research-draft.md" \
     "continue at MAP.md synthesis and atomic write" \
     --hash "$Z_HARNESS_PLAN_DIR/MAP.md"
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
   explore_checkpoint_seam map-phase5-pre-final-review \
     "$Z_HARNESS_PLAN_DIR/MAP.md" \
     "continue at MAP.md final review and citation checks"
   ```

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
- **deep**: `MAP.md` was written in Phase 4 step 4.

- **Citation enforcement:** Findings without a `file:line` match are demoted to `## Gaps` by the synthesis phase. Count demoted findings as `GAP_COUNT` and cited findings as `CITATION_COUNT` for telemetry. Both counts are included in the `explore_run_end` payload.

Log run end with telemetry, including citation and gap counts (tracked during Phase 4 synthesis):

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" explore_run_end \
  "$(printf '{"slug":"%s","depth":"%s","explores_dispatched":%d,"explores_succeeded":%d,"explore_calls":%d,"explore_failures":%d,"citation_count":%d,"gap_count":%d,"map_written":%s,"critique_status":"%s","status":"%s"}' \
     "$Z_HARNESS_SLUG" "$EXPLORE_DEPTH" "${EXPLORES_DISPATCHED:-0}" "${EXPLORES_SUCCEEDED:-0}" "${EXPLORES_SUCCEEDED:-0}" "$(( ${EXPLORES_DISPATCHED:-0} - ${EXPLORES_SUCCEEDED:-0} ))" "${CITATION_COUNT:-0}" "${GAP_COUNT:-0}" "${MAP_WRITTEN:-false}" "${CRITIQUE_STATUS:-none}" "<complete|complete_no_critique|scout>")"
```

After final review accepts `MAP.md` (deep mode) and `explore_run_end` telemetry is durable, checkpoint before user-facing report generation:
```bash
explore_checkpoint_seam map-phase5-pre-user-report \
  "$Z_HARNESS_PLAN_DIR/MAP.md" \
  "continue at final user-facing report"
```

**Run Brief + teardown funnel.** Set outcome/next, then tear down (releases the never-held claim, deregisters, emits `run_end`):

```bash
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "<one sentence, e.g. 'Deep terrain mapped: MAP.md written, 12 cited findings, 2 gaps.'>"
bash "$RB_SH" set-section --run "$RUN" --section next --json /dev/stdin <<'JSON'
{"label": "<pick the single strongest next step for this depth>", "command": "<e.g. /z-plan, or null for quick scouts>"}
JSON
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" \
  --run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-explore --status complete
```

If policy allows (`config.py should-notify --event phase_end` = `yes`), push the run-brief-rendered summary — never author independent push prose:

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ]; then
  PUSH_BODY="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  PushNotification("$PUSH_BODY")
fi
```

The assistant's own chat response (not the push) still surfaces the full, depth-specific `## Next` menu from the artifact/inline output above — that routing judgment is preserved verbatim; only the async push notification renders from run-brief.

## Hard rules

- **Terrain mapping, not direction picking.** The `## No-recommendation` section is invariant for deep and standard modes. Quick mode explicitly states the scout nature.
- **Citations are non-negotiable.** No `file:line` → not a finding.
- **Depth discipline.** Respect the selected depth. Quick means fast and lightweight; deep means thorough with critique.
- **Cost discipline.** Quick mode skips the cost gate entirely. Deep mode has the full gate. Exceeding 2M tokens logs a `cost_warning`.
- **Log everything.** Every Explore dispatch, consultant call, demotion, halt — via `scripts/log-event.sh`.
- **No exit past the funnel.** Complete → Finalize's teardown call; everything else after preflight → `explore_halt`.

---

Driver support requirements: see frontmatter `driver_features_required`. Non-supporting drivers **must surface and skip** any gated block — silent omission is forbidden. Each gated call site carries its own `<!-- RUNTIME-GATE: ... -->` comment immediately before the call; that is the single source of truth (SKILL-STYLE.md §1 — the closing conformance table is retired for rewritten skills).
