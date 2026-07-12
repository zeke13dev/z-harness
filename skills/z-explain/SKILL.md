---
name: z-explain
disable-model-invocation: false
description: One-shot structured explanation of code or repo orientation at a chosen depth lens. Supports --repo orientation and --surface policy. Citations required. Handoff to /z-learn when interactive exploration is warranted; route completed-work reports to /z-report. Read-only, no cross-LLM consult.
argument-hint: "--repo [orientation|walkthrough|audit-brief] [--surface=auto|off|force] | <target> [orientation|walkthrough|deep|audit-brief] [--surface=auto|off|force] or free-text"
runtime: c1
driver_features_required:
  - subagent
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-explain`** — a lightweight, one-shot code/system explainer for understanding behavior, structure, or implementation details. It delivers ONE structured answer at the requested depth, with file:line citations. `/z-explain --repo orientation` is the one-shot repo-orientation path; it still produces one answer at one lens. When the topic warrants ongoing exploration, you recommend `/z-learn` and stop. For completed-work narratives, evidence summaries, backtests, feature writeups, technical handoffs, or external/shareable reports, route to `/z-report` instead. You do not run an interactive loop.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

## The four lenses (shared with `/z-learn`)

Every explanation uses exactly one lens per invocation. Fuzzy natural language maps to these; explicit keywords win when present.

| Lens | User signals | Delivers |
|------|--------------|----------|
| **orientation** | "high level", "overview", "why", "design decisions" | What this is, why it exists, key design choices and tradeoffs |
| **walkthrough** | "how does it work", "flow", "pipeline", "end to end" | Data/control flow through main components in execution order |
| **deep** | "more detail", "line by line", "this function", "tell me about X" | Line-level behavior on the named symbol, block, or file region |
| **audit-brief** | "audit", "what could break", "invariants", "edge cases" | Invariants, failure modes, assumptions, what to verify — **not** a real audit |

Default lens when ambiguous: **orientation**.

**Audit-brief disclaimer:** This lens prepares the user to audit; it does not find bugs. Route "is this wrong?" / "find issues" to `/z-audit`.

## Setup

1. **Resolve plans base** (for learn handoff staging):
   ```bash
   PLANS_BASE="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" base_dir)"
   mkdir -p "$PLANS_BASE"
   ```
2. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-explain`.
3. `export Z_HARNESS_SLUG=adhoc`
4. Archive dir (aligned with `log-event.sh` slug namespacing):
   ```bash
   CURRENT_ARCHIVE_DIR="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path adhoc)/archive/$RUN"
   mkdir -p "$CURRENT_ARCHIVE_DIR"
   ```
5. **Version stamp + log:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["arguments"] = sys.argv[2]; v["command"] = "z-explain"
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" explain_run_start "$START_PAYLOAD"
   ```
6. Notification policy: see [docs/human/config.md](docs/human/config.md) (`notify.level` key). `/z-explain` is low-noise — no push on completion unless policy demands it.

## Phase 0 — Route check (before reading code)

Run this when intent clearly mismatches a one-shot explanation:

| Signal | Route to |
|--------|----------|
| Code terrain reconstruction: "where does X live?", "map the codebase", "find entry points/seams" | `/z-explore <target> --depth=quick|standard|deep` |
| Find bugs / correctness issues | `/z-audit <target>` |
| Change or fix code | `/z-plan --quick <task>` or `/z-plan <task>` |
| Multi-turn tutoring already needed ("walk me through everything", "keep going") | `/z-learn <target>` |
| Completed-work narrative, evidence summary, backtest writeup, technical handoff, or external/shareable report | `/z-report <target> <profile>` |
| Work-thread recovery/reorientation: "what was I doing?", "where did that run/branch/worktree end up?", "how do I continue safely?" | `/z-resume <topic|--slug|--run|--branch|--worktree>` |

If routing, write `$CURRENT_ARCHIVE_DIR/route-decision.md` with the reason, log `explain_route_handoff`, recommend the command, and **stop**. Do not auto-dispatch.

## Phase 1 — Parse target, lens, and surface policy

1. **Surface policy** — parse `--surface=auto|off|force`; default is `auto`. Unknown values are invalid usage: state the accepted values and stop without guessing.
   - `auto` may use surface mapping when it improves broad-target grounding.
   - `off` disables surface mapping entirely and preserves the current grounding path: doc-fetcher / plan precontext, then minimum direct reads or one focused Explore exactly as before. Do not run `scripts/surface-map.py`, do not dispatch the repo surface Explore batch, and do not write `surface-map.json`.
   - `force` runs surface mapping for any non-empty target before direct reads, while still falling back to current grounding if mapping fails.
2. **Repo flag** — if `--repo` is present, set `TARGET="<repo root>"` and `TARGET_KIND=repo`. `/z-explain --repo orientation` is the canonical repo-orientation invocation.
3. **Target** — otherwise one of: file path, module/crate name, symbol (`fn foo`, `class Bar`), plan slug, or free-text topic ("order ingestion pipeline").
4. **Lens** — from explicit keyword in args, or infer from fuzzy NL (see table above). State the chosen lens in your response header: `Lens: orientation` (etc.). `--repo` defaults to `orientation`; it accepts `orientation`, `walkthrough`, or `audit-brief`. `deep` is invalid with `--repo` unless the user also names a narrower file, symbol, directory, or subsystem focus.
5. **Baseline calibration (optional, one line):** If the user gave no depth signal, assume they are new to the area unless context suggests otherwise.

If args are empty, ask one question: "What should I explain — file, module, pipeline, topic, or `--repo orientation`?" Do not proceed without a target.

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the empty-args
     target prompt via their native channel. Silent omission is forbidden. -->

## Phase 2 — Grounding

1. If `docs/llm/INDEX.json` exists, dispatch doc-fetcher once for the target topic:

<!-- RUNTIME-GATE: subagent; non-supporting drivers skip doc-fetcher and read docs/human/ directly if needed. -->
```
Agent(
  subagent_type="doc-fetcher",
  description="Explain grounding for <target>",
  prompt="I need context on: <target>\n\nReturn a tight synthesis with file:line markers for the orchestrator."
)
```

2. If the target is a **plan slug** (matches an entry from `all_plan_slugs`, or resolves via `resolve_plan_path`), read precontext from that plan dir — do **not** use `$Z_HARNESS_PLAN_DIR` (logging slug stays `adhoc`):
   ```bash
   TARGET_SLUG="<derived slug>"
   TARGET_PLAN_DIR="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$TARGET_SLUG")"
   ```
   Read `$TARGET_PLAN_DIR/MAP.md`, `$TARGET_PLAN_DIR/SPEC.md`, `$TARGET_PLAN_DIR/GRILL.md`, and `$TARGET_PLAN_DIR/LEARN.md` if present.

<!-- include: _fragments/surface-mapping.md -->

3. **Surface mapping branch** — run after doc-fetcher and plan precontext, before source reads:

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface the repo surface Explore dispatch requirement and skip the live surface batch if unavailable. Existing grounding, including `--surface=off`, must continue with a warning. -->
   - **`--surface=off`** — skip this branch and continue with step 4. This is the compatibility path and must preserve current grounding behavior.
   - **`--repo` with `auto` or `force`** — dispatch one parallel batch of three Explore facets, using the shared facet prompts above: top-level structure; entry points and runtime surfaces; key modules and seams. Each facet returns only cited findings (`file:line`), no recommendations.
     - Merge the three facet returns into `$CURRENT_ARCHIVE_DIR/surface-map.json` using the shared schema: `mode=repo`, `caller=z-explain`, `target.raw="$ARGUMENTS"`, `target.inferred_kind=repo`.
     - Put entrypoint/runtime facts in `primary` with relation `entrypoint` or `exports`; structural directories and docs/tests in `related`; subsystem boundaries in `clusters`; first-read pointers in `suggested_reads`.
     - Set `status=ok` only when all three facets returned cited findings within caps; `partial` when at least one facet is useful but another is missing; `truncated` or `too_broad` when caps cut coverage; `error` when the batch failed. Keep warnings explicit.
     - Ignore uncited Explore claims until direct reads verify them.
   - **Non-`--repo` broad target with `auto` or any target with `force`** — call deterministic preflight when it helps target reads:
     ```bash
     python3 scripts/surface-map.py --repo-root "$PWD" --target "<target>" --mode symbol --caller z-explain --out "$CURRENT_ARCHIVE_DIR/surface-map.json"
     ```
     Use `ok` / `partial` maps as a reading guide only. If the status is `error`, `not_found`, `ambiguous`, `too_broad`, or `truncated`, surface the warning and fall back to step 4 unless the user explicitly asked for surface-only narrowing.
   - **Exact file/range target with `auto`** — keep the current direct-read path unless `--surface=force`.
4. Read the minimum source files needed for the chosen lens. Use Read/Grep/Glob directly for ≤3 files; use Explore (Haiku) for broader targets:
```
Agent(
  subagent_type="Explore",
  model: "haiku",
  description="Explain read: <target>",
  prompt="Target: <target>\nLens: <lens>\nSurface map: <none|$CURRENT_ARCHIVE_DIR/surface-map.json>\n\nReturn facts needed for ONE <lens> explanation. Every code claim needs file:line citations. Be terse."
)
```

Save a one-paragraph grounding note to `$CURRENT_ARCHIVE_DIR/grounding.md`, including `surface_map_status` and `surface_map_path` when a map exists.

## Phase 3 — Deliver one structured answer

Write exactly ONE explanation chunk. Structure by lens:

**orientation** — (1) purpose in one sentence, (2) key design decisions with rationale, (3) what it depends on / what depends on it, (4) 2-3 representative citations.

**orientation with `--repo`** — one-shot repo orientation only, not an atlas: (1) project shape in one paragraph, (2) top-level structure, (3) entry points and runtime surfaces, (4) key modules/seams, (5) where to read next, (6) optional `/z-learn --repo` handoff. Every factual claim must cite source lines from the surface facets or direct reads.

**walkthrough** — numbered steps in execution/data order; each step names the component and cites entry points; end with a one-line "where to read next" pointer.

**deep** — scope boundary (what you are explaining), then behavior section-by-section with citations; call out non-obvious branches and side effects.

**audit-brief** — invariants, failure modes, assumptions, observability hooks, and a short "verification checklist" (what to trace, what to grep, what to test). Label clearly: *Audit-ready understanding — not findings.*

**Citation contract:** Every factual code claim gets `file:line`. High-level summaries still anchor to representative lines.

**Surface failure/truncation behavior:** If `surface-map.json` is `too_broad`, `truncated`, `ambiguous`, or has multiple unrelated clusters, give a bounded orientation only for cited facts that remain honest. Otherwise ask the user to narrow. For repo orientation, recommend `/z-learn --repo` for progressive exploration; experimental terrain mapping is dev-only and must not be invoked by default. If status is `error`, show a short warning and use the current non-surface grounding path.

## Phase 4 — Handoff and finalize

1. **Continue gate.** If the topic is multi-component, the user asked an open-ended question, or the answer ends with natural "deeper" branches, recommend:

   > Continue interactively: `/z-learn <same-target>`

   For repo orientation, prefer:

   > Continue interactively: `/z-learn --repo`

   If the user is coming from `/z-report`, focus on the requested code-level study only. Do not restate the report as a tutorial; explain the named file, symbol, subsystem, or flow.

   Optionally seed `$PLANS_BASE/.learn-pending.md` so `/z-learn` does not repeat work. Use the **shared staging schema** (below). Only write if the file does not exist, or if it exists for the **same** `target:` — do not overwrite an active learn session on a different target without warning.

   **Shared `.learn-pending.md` schema** (contract with `/z-learn`):
   ```markdown
   # Learn session (pending)
   target: <target string>
   started: <iso8601 UTC>
   current_lens: <lens used in this explain>
   last_focus: <one-line focus from this answer>
   surface_map_path: <archive path or none>

   ## Prior explain
   lens: <orientation|walkthrough|deep|audit-brief>
   summary: <1-3 sentence takeaway>
   citations:
   - <file:line>
   - ...

   ## Turn log
   ```
   When seeding from `/z-explain`, write the header + `surface_map_path` when present + `## Prior explain` + an empty `## Turn log` section. Do not append turn entries — `/z-learn` owns the turn log.

2. **Log completion:**
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" explain_run_end \
     "$(printf '{"lens":"%s","target":"%s","handoff_learn":%s}' "$LENS" "$TARGET" "$HANDOFF")"
   ```
3. Brief summary to user: lens used, 1-line takeaway, handoff hint if any.

## Out of scope
- **Interactive tutoring.** That is `/z-learn`.
- **Code terrain reconstruction.** That is `/z-explore`; `/z-explain --repo orientation` remains a one-answer orientation path, not a MAP/terrain survey.
- **Finding bugs.** That is `/z-audit`.
- **Cross-LLM consult.** One orchestrator pass keeps cost low.
- **Writing LEARN.md.** Only `/z-learn` finalizes study artifacts.
- **Completed-work reporting.** Evidence summaries, feature writeups, backtests, technical handoffs, and external/shareable reports are `/z-report`.
- **Work-thread recovery.** That is `/z-resume`; `/z-explain` may teach a selected code surface after recovery, but it does not select prior plan/run/worktree state.

## Hard rules

- **One answer, one lens.** Do not dump all four lenses in one response; `--repo` changes grounding breadth, not the one-answer contract.
- **Citations on every code claim.**
- **Handoff is advisory** — never auto-dispatch `/z-learn`.
- **No emojis** anywhere.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Phase 2 doc-fetcher + Explore |
| `ask_user` | yes | Phase 1 empty-args target prompt only |
| `skill_invoke` | no | — |

Non-supporting drivers **must surface and skip** any gated block — silent omission is forbidden.
