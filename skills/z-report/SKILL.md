---
name: z-report
disable-model-invocation: false
description: "Depth-tiered narrative of exactly what happened + what follow-ups exist, for a z-harness run or past work (run-id / plan-slug / PR / commit-range). User-invoked, read-only, composes existing reporting primitives. Does not auto-fire."
argument-hint: "[target|current|changes|since <ref>] [summary|standard|deep] [--surface=auto|off|existing|refresh] | --run <id> --slug <s> --pr <N|url> --range <A..B> --base <ref> --save <path>"
runtime: c1
driver_features_required:
  - subagent
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-report`** — a depth-tiered narrative of exactly what happened and what follow-ups exist for a z-harness run or past work. Read-only; never edits the target repo beyond writing `REPORT.md` or the `--save` path.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

## Setup

1. **Logging namespace:** `export Z_HARNESS_SLUG=adhoc`
2. **Run id:** `RUN=$(date -u +%Y%m%dT%H%M%SZ)-report`
3. **Archive dir:**
   ```bash
   CURRENT_ARCHIVE_DIR="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path adhoc)/archive/$RUN"
   mkdir -p "$CURRENT_ARCHIVE_DIR"
   ```
4. **Version stamp + log start:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["arguments"] = sys.argv[2]; v["command"] = "z-report"
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" report_run_start "$START_PAYLOAD"
   ```
5. Notification policy: `/z-report` is low-noise — no push on completion unless policy demands it. See [docs/human/config.md](docs/human/config.md) (`notify.level` key).

## Phase 0 — Parse target, depth, and surface policy

**Depth** is one of `summary | standard | deep`. Resolve from `$ARGUMENTS` as follows:
- If an explicit keyword (`summary`, `standard`, `deep`) appears, use it.
- If fuzzy NL signals a tier (e.g., "brief", "quick" → summary; "full", "verbose" → deep), map it.
- Default (no signal): `standard`.

Record the chosen tier as `TIER`.

**Surface policy** is one of `auto | off | existing | refresh`. Resolve from `$ARGUMENTS` as follows and record the chosen value as `SURFACE_POLICY`:
- Default: `auto`.
- `off` disables surface-map attachment entirely. `context.json` may still contain ordinary report fields, but no fresh or existing `surface_map_*` fields are required.
- `existing` consumes only already-assembled surface artifacts that `scripts/report-context.py` can attach to `context.json`; it never runs a fresh mapper.
- `refresh` allows `scripts/report-context.py` to produce fresh deterministic `diff` surface data where the tier policy permits. For run/slug historical reports, any refreshed surface must be labeled as report-time current repo state, not historical truth.
- `auto` applies the tier policy below.

**Surface tier policy:**
- `summary` consumes existing surface data only. It must not trigger live surface refresh, even with diff-backed targets.
- `standard` and `deep` diff-backed reports (`pr`, `range`, `base`, `worktree`, `current`, `changes`, `since <ref>`) may attach fresh deterministic `diff` surface data unless `--surface=off` or `--surface=existing`.
- `run` and `slug` reports consume existing surface artifacts unless `--surface=refresh` is explicit and the selected tier is `standard` or `deep`.
- Missing, failed, truncated, or skipped surface data is non-fatal; render any warning from `context.json` and continue with the normal report.

**Repo-state aliases (T006 resolver contract):**
- `/z-report current [summary|standard|deep] [--surface=auto|off|existing|refresh]` resolves to the existing worktree report mode.
- `/z-report changes [summary|standard|deep] [--surface=auto|off|existing|refresh]` is an alias for `current` / worktree mode.
- `/z-report since <ref> [summary|standard|deep] [--surface=auto|off|existing|refresh]` resolves to the existing `--base <ref>` / range diff mode; the wrapper below normalizes this alias before invoking `report-context.py`.
- `/z-report --base <ref> --surface=auto [standard|deep]` is the canonical explicit diff-backed invocation for fresh deterministic surface attachment.
- Unknown `--surface` values are invalid usage: state the accepted values and stop without guessing.

T006 provides native parser/context support for these aliases, `--tier`, and `--surface`.

**Target resolution** — delegate to `scripts/report-context.py --resolve-only` with the same target, tier, and surface policy that Phase 1 will use. Build target arguments by removing `/z-report` control flags (`--save`, `--tier`, `--surface`) and positional depth tokens, then append the normalized `--tier "$TIER"` and `--surface "$SURFACE_POLICY"` flags explicitly.

Normalize `since <ref>` to the supported `--base <ref>` form; keep already-supported explicit target flags unchanged.

```bash
REPORT_CONTEXT_TARGET_ARGS="$(python3 - "$ARGUMENTS" <<'PY'
import shlex, sys

tokens = shlex.split(sys.argv[1])
out = []
skip_next = False
depths = {"summary", "standard", "deep"}

for idx, tok in enumerate(tokens):
    if skip_next:
        skip_next = False
        continue
    if tok in depths:
        continue
    if tok in {"--surface", "--tier", "--save"}:
        skip_next = True
        continue
    if tok.startswith("--surface=") or tok.startswith("--tier=") or tok.startswith("--save="):
        continue
    if tok == "since" and idx + 1 < len(tokens):
        out.extend(["--base", tokens[idx + 1]])
        skip_next = True
        continue
    out.append(tok)

print(shlex.join(out))
PY
)"
DESCRIPTOR="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/report-context.py" \
  --resolve-only $REPORT_CONTEXT_TARGET_ARGS \
  --tier "$TIER" \
  --surface "$SURFACE_POLICY" 2>&1)"
RESOLVE_EXIT=$?
```

Parse the JSON descriptor from `$DESCRIPTOR`. Extract the `mode` field:

- **`mode: ambiguous`** — surface the descriptor's `message` field to the user and ask for clarification.

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the
     ambiguous-target question (the script's `message` field) via their native channel. Silent
     omission is forbidden. -->

  Invoke AskUserQuestion with the script's `message` field, appended with the following clarification prompt:

  > Please clarify using an explicit flag:
  > - `--run <run-id>` — ISO timestamp prefix, e.g. `20260101T120000Z-plan`
  > - `--slug <plan-slug>` — kebab-case slug, e.g. `my-feature`
  > - `--pr <N|URL>` — PR number or `github.com/.../pull/N` URL
  > - `--range <A..B>` — git range, e.g. `main..HEAD`
  > - `--base <ref>` — feature-branch diff against ref
  > - `current` or `changes` — current worktree diff
  > - `since <ref>` — diff since the named base ref
  > - `--surface=auto|off|existing|refresh` — surface-map policy

  After the user responds, re-run Phase 0 with the clarified input. Do not proceed with an ambiguous descriptor.

- **`mode: not_found`** — print the descriptor's `message` field as an actionable error and stop:
  ```
  Error: <message from descriptor>
  No matching run, plan, PR, or commit found for the given target. Correct the target and try again.
  ```
  Do not proceed.

- **`mode: run | slug | pr | range | base | worktree`** — target is resolved. Record `MODE`. Assign the resolved descriptor JSON to a named variable for use in later phases:

  ```bash
  DESCRIPTOR_JSON="$DESCRIPTOR"
  ```

  Proceed to Phase 1.

## Phase 1 — Assemble context bundle

Call `scripts/report-context.py` (full run, no `--resolve-only`) to compose the deterministic context bundle. Pass the normalized target arguments plus `--tier "$TIER"`, `--surface "$SURFACE_POLICY"`, and `--out`. `scripts/report-context.py` is the only place that may attach surface data; render branches consume only the fields present in the resulting `context.json`.

```bash
CONTEXT_PATH="$CURRENT_ARCHIVE_DIR/context.json"
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/report-context.py" \
  $REPORT_CONTEXT_TARGET_ARGS \
  --tier "$TIER" \
  --surface "$SURFACE_POLICY" \
  --out "$CONTEXT_PATH" 2>&1
CONTEXT_EXIT=$?
```

If `$CONTEXT_EXIT` is non-zero, record `CONTEXT_PATH=""` and proceed — the inline fallback in Phase 2 handles missing context.

Read the written `context.json` to extract the size-gate fields:

```python
import json, pathlib
ctx = json.loads(pathlib.Path("$CONTEXT_PATH").read_text()) if "$CONTEXT_PATH" else {}
DIFF_BYTES   = ctx.get("diff_bytes", 0)
EVENTS_CHARS = ctx.get("events_chars", 0)
RUN_BRIEF_PRESENT = ctx.get("run_brief_present", False)
SURFACE_MAP_STATUS = ctx.get("surface_map_status", "omitted")
SURFACE_MAP_SUMMARY = ctx.get("surface_map_summary", "")
SURFACE_MAP_WARNINGS = ctx.get("surface_map_warnings", [])
```

Record `DIFF_BYTES`, `EVENTS_CHARS`, `RUN_BRIEF_PRESENT`, `SURFACE_MAP_STATUS`, `SURFACE_MAP_SUMMARY`, and `SURFACE_MAP_WARNINGS` for Phase 2.

Resolve `RUN_DIR` once here for use in Phase 2 Branch A and Phase 3 Step 2:

```bash
RUN_DIR=""
if [ "$MODE" = "run" ] || [ "$MODE" = "slug" ]; then
  RUN_DIR="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("run_dir",""))' "$DESCRIPTOR_JSON")"
fi
```

## Phase 2 — Render

### Branch A — Fast path (run-brief chat render)

If **all three** of the following are true:
- `MODE == "run"`
- `TIER == "summary"`
- `RUN_BRIEF_PRESENT` is true

Apply the defensive guard before invoking the renderer (`RUN_DIR` was resolved at the end of Phase 1):

If `RUN_DIR` is empty or the directory does not exist, **skip the fast path entirely and proceed to Branch C** (report-synth). Do not invoke `render-run-brief.py` with an empty or missing `--run-dir` — it would fail silently or produce no output.

Otherwise capture the fast-path render as `NARRATIVE` and skip the subagent entirely:

```bash
NARRATIVE="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py" \
  --run-dir "$RUN_DIR" --format chat)"
```

Append any fast-path `## Surface Map` section to `NARRATIVE` before proceeding to Phase 3. If `context.json` includes `surface_map_summary` or `surface_map_warnings`, append the section after the run-brief render using only `context.json` fields (`surface_map_status`, `surface_map_source`, `surface_map_summary`, `surface_map_generated_at`, and `surface_map_warnings`). The fast path must not read `surface_map_path`, run discovery, or refresh surface data; summary-tier surface facts are existing-only. Set `FELL_BACK_INLINE=false`.

Do not dispatch `report-synth` when the fast path fires.

### Branch B — Size gate

If **either** of the following size conditions is true AND `TIER` is `standard` or `deep`:
- `DIFF_BYTES > 102400`
- `EVENTS_CHARS > 512000`

Compute a human-readable size label:

```python
size_label = []
if DIFF_BYTES > 102400:
    size_label.append(f"diff {DIFF_BYTES // 1024}KB")
if EVENTS_CHARS > 512000:
    size_label.append(f"events {EVENTS_CHARS // 1000}K chars")
SIZE_DESC = ", ".join(size_label)
```

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the large-context
     size-gate question via their native channel before proceeding with synthesis. Silent omission is forbidden. -->

Present an `AskUserQuestion`:

> **Large context detected** (`SIZE_DESC`): the assembled bundle exceeds the recommended threshold for a `TIER`-tier report. Choose how to proceed:
>
> 1. **Proceed** — run `report-synth` at `TIER` tier as requested (may consume significant tokens).
> 2. **Downgrade** — run `report-synth` at the next-lower tier (`standard` → `summary`; `deep` → `standard`).
> 3. **Summary only** — use the fast-path inline digest (no subagent, deterministic output only).

On the user's answer:
- **Proceed** — continue to Branch C with the original `TIER`.
- **Downgrade** — set `TIER` to the next-lower tier and continue to Branch C.
- **Summary only** — set `FELL_BACK_INLINE=true` and jump to Branch D.

If the size gate does **not** fire (sizes are within threshold, OR tier is `summary`), proceed directly to Branch C.

### Branch C — Synthesis via report-synth subagent

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to the user and skip
     the Agent() call. When subagents are unavailable, fall through to Branch D (inline fallback). -->

```
Agent(
  subagent_type="report-synth",
  description="Synthesize z-report narrative for <MODE> target at <TIER> tier",
  prompt="context_path: <CONTEXT_PATH>\ntier: <TIER>\nmode: <MODE>\nsurface_contract: Use only context.json surface_map_* fields for any Surface Map discussion. Do not read surface_map_path, invoke discovery, or call sibling z-harness commands."
)
```

Capture the subagent's return text as `SYNTH_OUTPUT`.

If the subagent is unavailable (driver does not support `subagent`) OR `SYNTH_OUTPUT` starts with `INSUFFICIENT_CONTEXT:` OR `SYNTH_OUTPUT` is empty, fall through to Branch D.

Otherwise set `NARRATIVE = SYNTH_OUTPUT` and `FELL_BACK_INLINE=false`. Proceed to Phase 3.

`report-synth` may include a compact `Surface Map` section only when `context.json` contains `surface_map_summary` and/or `surface_map_warnings`. It must label `surface_map_source=report_time_current_repo` as report-time current state, not historical truth for run/slug reports.

### Branch D — Inline deterministic digest fallback

Used when: subagent support is absent, `report-synth` returns the `INSUFFICIENT_CONTEXT:` marker, `SYNTH_OUTPUT` is empty, or the user chose "Summary only" in the size gate.

Set `FELL_BACK_INLINE=true`.

Read `context.json` (or use an empty dict if missing) and render the following sections directly, in order, with no LLM synthesis and no reads from `surface_map_path`.

**0. Incomplete-context banner (conditional)**

Before rendering any sections, check whether the bundle is degraded: if `ctx.get("message")` is present OR `ctx.get("warnings")` is non-empty (a non-empty list), print the following banner at the very top of the output, before the status line:

```
NOTE: incomplete context — this report may be missing data.
<ctx["message"] if present>
<for each warning in ctx["warnings"]: "- <warning>">
```

Omit the banner entirely if both `ctx.get("message")` is absent (or None) and `ctx.get("warnings")` is empty or absent. Do not print the banner for a fully populated bundle.

**1. Status line**

Derive a human-readable generation timestamp from `$RUN` (format: `YYYYMMDDTHHMMSSZ-report`). Extract the datetime prefix and reformat it for display:

```bash
REPORT_GENERATED_AT="$(python3 -c '
import sys, re
run = sys.argv[1]
m = re.match(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", run)
if m:
    Y,Mo,D,H,Mi,S = m.groups()
    print(f"{Y}-{Mo}-{D}T{H}:{Mi}:{S}Z")
else:
    print(run)
' "$RUN")"
```

```
Target: <MODE> — <run_dir or pr or range from DESCRIPTOR_JSON>
Status: <ctx["status"] if present else "unknown">
Generated: <REPORT_GENERATED_AT>
```

**2. Decision table**

```markdown
## Decisions
```

If `ctx["decisions"]` is non-empty, render as a markdown table:

| Task | Kind | Summary |
|------|------|---------|
| `<task_id>` | `<decision_kind>` | `<summary>` |

If absent or empty: `No decisions recorded.`

**3. Follow-up table**

```markdown
## Follow-Ups
```

If `ctx["followups"]` is non-empty, render as a markdown list:
```
- <follow-up text>
```

If `ctx["followups_note"]` is present, append it as a blockquote.
If absent or empty: `No open follow-ups recorded.`

**4. Surface Map (conditional)**

Render this section only when at least one of `ctx["surface_map_summary"]`, `ctx["surface_map_status"]`, or `ctx["surface_map_warnings"]` is present and non-empty:

```markdown
## Surface Map
```

Use only these `context.json` fields:
- `surface_map_status`
- `surface_map_source`
- `surface_map_summary`
- `surface_map_generated_at`
- `surface_map_warnings`

If `surface_map_summary` is present, render it as the body. If `surface_map_source` is `report_time_current_repo`, prefix the body with: `Report-time current repo state, not historical run truth.` If warnings are present, render them as bullets. If the status is `failed`, `truncated`, `skipped`, or `omitted`, state the status plainly and do not infer missing coverage. Never read `surface_map_path` from the inline fallback.

**5. Cost line**

```markdown
## Cost
```

If `ctx["cost"]` is non-empty, render each subagent row:
```
- <subagent>: input=<n> output=<n> est=<$n> <[char-est] if flagged>
```

If absent or empty: `Cost data not available.`

**6. Phase wall-time table**

```markdown
## Phase Wall-Time
```

If `ctx["phases"]` is non-empty, render as a markdown table:

| Phase | Wall time | User wait |
|-------|-----------|-----------|
| `<name>` | `<wall_ms>ms` | `<user_wait_ms>ms` |

Omit the `User wait` column if no phase has a `user_wait_ms` field.
If absent or empty: `No phase timing data available.`

Set `NARRATIVE` to the concatenation of these sections.

## Phase 3 — Output + finalize

**Step 1 — Print narrative to chat (always).**

Print `NARRATIVE` to the chat channel unconditionally, regardless of `MODE`, `TIER`, or `FELL_BACK_INLINE`.

Initialize:

```bash
SAVED=false
```

**Step 2 — Write `REPORT.md` for run/slug targets.**

If `MODE` is `run` or `slug`:

If `RUN_DIR` is non-empty and the directory exists:

```bash
REPORT_PATH="$RUN_DIR/REPORT.md"
REPORT_TMP="$RUN_DIR/.REPORT.md.tmp.$$"
printf '%s\n' "$NARRATIVE" > "$REPORT_TMP"
mv "$REPORT_TMP" "$REPORT_PATH"
SAVED=true
```

Use atomic tmp+rename (`mv`) so a partial write never leaves a corrupt `REPORT.md`.

If `RUN_DIR` is empty or does not exist, skip this step (leave `SAVED=false`).

**Step 3 — Write `--save <path>` (any mode).**

If the user passed `--save <path>` in `$ARGUMENTS`, extract the path:

```bash
SAVE_PATH="$(python3 -c '
import sys, re
m = re.search(r"--save\s+(\S+)", sys.argv[1])
print(m.group(1) if m else "")
' "$ARGUMENTS")"
```

If `SAVE_PATH` is non-empty:

```bash
SAVE_TMP="${SAVE_PATH}.tmp.$$"
printf '%s\n' "$NARRATIVE" > "$SAVE_TMP"
mv "$SAVE_TMP" "$SAVE_PATH"
SAVED=true
```

If both Step 2 and Step 3 apply, both writes occur; `SAVED=true` for the log. A prior `SAVED=true` from Step 2 is never reset to false by Step 3.

**Step 4 — Log `report_run_end`.**

Extract a target identifier from the descriptor (the most specific non-empty field: `run_dir` for run/slug modes, `pr` for pr mode, `range` for range/base modes, otherwise the raw arguments):

```bash
TARGET_ID="$(python3 -c '
import json, sys
d = json.loads(sys.argv[1])
mode = d.get("mode", "")
if mode in ("run", "slug"):
    print(d.get("run_dir", "") or d.get("slug", ""))
elif mode == "pr":
    print(str(d.get("pr", "")))
elif mode in ("range", "base"):
    print(d.get("range", "") or d.get("base", ""))
else:
    print(d.get("target", ""))
' "$DESCRIPTOR_JSON")"
```

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" report_run_end \
  "$(python3 -c '
import json, sys
mode, tier, target, saved, fell_back = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
print(json.dumps({
  "mode": mode,
  "tier": tier,
  "target": target,
  "saved": saved == "true",
  "fell_back_inline": fell_back == "true"
}))
' "$MODE" "$TIER" "$TARGET_ID" "$SAVED" "$FELL_BACK_INLINE")"
```

**Step 5 — Advisory handoffs (prose only; never invoked).**

After the narrative, print advisory recommendations where applicable. These are prose suggestions printed by `/z-report` — they are **not** automatic dispatches or invocations of sibling commands.

- If any of the following signals indicate process friction: `ctx["halts"]` is non-empty, OR `ctx["status"]` is `"halted"` or `"errored"`, OR any entry in `ctx["phases"]` has `wall_ms > 300000` (5 minutes): recommend `/z-improve` for a structured remediation pass.
  > To address the friction signals above, consider running `/z-improve` to generate targeted improvement proposals.
- If `NARRATIVE` or `ctx["followups"]` contains any open follow-up items: recommend `/z-followup-next`.
  > Open follow-ups were found. Run `/z-followup-next` to surface and triage the next actionable item.
- If the user's original question referenced a specific function, file, or symbol: recommend `/z-explain`.
  > For a deeper code-level walkthrough of any symbol above, run `/z-explain <symbol>`.

Print only the applicable advisories. Omit any advisory whose trigger condition is not met.

---

## Hard rules

1. **Read-only on the target repo.** `/z-report` writes only `REPORT.md` (at `<run-dir>/REPORT.md` for run/slug targets) and the `--save` path. No edits to any source file, config, plan artifact, or other path in the target repo.
2. **No sibling-command invocation.** `/z-report` never spawns, invokes, or auto-dispatches any other z-harness command (e.g., `/z-improve`, `/z-followup-next`, `/z-explain`). Handoffs to those commands are advisory prose recommendations only — the user invokes them.
3. **Every factual claim sourced from `context.json`.** All metrics, timings, decisions, costs, follow-ups, status values, and surface-map statements in the narrative must originate from the `context.json` bundle assembled in Phase 1 (which is itself derived from events/metrics/artifacts/diff and attached surface fields). Renderers must use only `context.json` `surface_map_*` fields for surface claims; they must not read `surface_map_path`, invoke discovery, or infer coverage from omitted data.
4. **No emojis.** The narrative and all printed output must contain no emoji characters.
5. **One narrative, one tier per invocation.** A single `/z-report` call produces exactly one narrative at exactly one depth tier. Tier is resolved in Phase 0 and does not change after the size-gate decision.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---|---|---|
| `subagent` | yes | Phase 2 Branch C — `report-synth` dispatch |
| `ask_user` | yes | Phase 0 ambiguous target; Phase 2 Branch B large-context size gate |
| `skill_invoke` | no | — |

Non-supporting drivers **must surface and skip** any gated block — silent omission is forbidden. Each gated call site is annotated with a `<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
