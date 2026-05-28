---
description: Tiered bulk codebase quality uplift — decompose repo into components, run a repo-wide cross-cutting pass, dispatch per-component audits, produce per-component TASKS.md files, and drive sequential implementation via /z-implement-all.
argument-hint: [--components=<file>] [--component <path>] [--retry-bailed] [--refresh-component <name>] [--dimensions=<csv>] [--cross-cutting=skip] [--no-style]
model: opus
runtime: c1
driver_features_required:
  - subagent
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are running the **z-harness `/z-uplift`** pipeline.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

Strict, multi-phase. Do not skip phases. Do not edit production code directly — `/z-uplift` orchestrates audits and delegates implementation to `/z-implement-all`.

---

## Argument parsing

Parse `$ARGUMENTS` before doing anything else:

- `--components=<file>` → capture as `COMPONENTS_FILE`. Path to a newline-delimited list of component paths; bypasses auto-detection in Phase 1.
- `--component <path>` (repeatable) → collect each value into `EXTRA_COMPONENTS` list. Explicitly include one component path per flag occurrence.
- `--retry-bailed` flag → set `RETRY_BAILED=true` (default `false`). On re-invoke, re-attempts components in `bailed` state.
- `--refresh-component <name>` → capture as `REFRESH_COMPONENT`. Re-runs audit for one named component (overwrites its REPORT/TASKS); does NOT touch other components.
- `--dimensions=<csv>` → capture as `DIMENSIONS` (default `correctness,cleanliness,design`).
  **`perf` is deliberately excluded from the default set** to bound uplift cost — perf auditors are the most expensive dimension and rarely surface fixable findings during bulk uplift. Pass `--dimensions=correctness,cleanliness,design,perf` to include it explicitly.
- `--cross-cutting=skip` → set `CROSS_CUTTING_SKIP=true` (default `false`). Skips Phase 2; escape hatch for tiny repos.
- `--no-style` → set `NO_STYLE=true` (default `false`). Bypasses the STYLE.md gate; cleanliness+design audits fall back to the generic rubric.

Initialize variables before the parsing loop (required for `set -u` compatibility):

```bash
EXTRA_COMPONENTS=()
COMPONENTS_FILE=""
RETRY_BAILED=false
REFRESH_COMPONENT=""
DIMENSIONS="correctness,cleanliness,design"
CROSS_CUTTING_SKIP=false
NO_STYLE=false
```

Parse `$ARGUMENTS` token-by-token:

```bash
_args=($ARGUMENTS)
_i=0
while [ $_i -lt ${#_args[@]} ]; do
  _arg="${_args[$_i]}"
  case "$_arg" in
    --components=*)    COMPONENTS_FILE="${_arg#--components=}" ;;
    --component)       _i=$((_i+1)); EXTRA_COMPONENTS+=("${_args[$_i]}") ;;
    --component=*)     EXTRA_COMPONENTS+=("${_arg#--component=}") ;;
    --retry-bailed)    RETRY_BAILED=true ;;
    --refresh-component) _i=$((_i+1)); REFRESH_COMPONENT="${_args[$_i]}" ;;
    --dimensions=*)    DIMENSIONS="${_arg#--dimensions=}" ;;
    --cross-cutting=skip) CROSS_CUTTING_SKIP=true ;;
    --no-style)        NO_STYLE=true ;;
  esac
  _i=$((_i+1))
done
```

---

## Setup

### Step 1 — Derive uplift slug

Derive a slug from the repository name or the first 2–4 words of the user's description: short kebab-case (e.g. "uplift my-app" → `my-app-uplift`; default `<repo-basename>-uplift`).

**First, run the slug collision check unconditionally** — check for an existing slug dir in the canonical plans directory (`z-harness/plans/`). This collision check is a hard prerequisite that is never bypassed by the resolver below.
- If a MANIFEST.md is found there, this is a **resume** — skip decomposition phases and jump to the next non-terminal MANIFEST state.
<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the slug collision confirmation question via their native channel. Silent omission is forbidden. -->
- If only a slug collision without MANIFEST, prompt the user to confirm or choose a different slug via `AskUserQuestion`.

After the collision check passes (no collision found, or the user confirmed a new slug), apply the soft non-obvious-slug confirmation gate. If the auto-derived slug is non-obvious, consult the resolver:

```bash
# Only reached after collision check has already passed.
RESOLVED="$(python3 scripts/config.py resolve-question workflow.slug_confirm)"
RESOLVE_EXIT=$?

if [[ $RESOLVE_EXIT -ne 0 ]]; then
  # Exit codes: 2=bad invocation, 3=unknown question_id, 4=I/O error.
  # In all error cases, fall through to ask the user normally — never silently skip.
  echo "resolve-question failed (exit $RESOLVE_EXIT); falling back to ask" >&2
  RESULT="ask"; DEFAULT=""; SOURCE="error"
else
  RESULT="$(echo "$RESOLVED" | jq -r .result)"
  DEFAULT="$(echo "$RESOLVED" | jq -r .default)"
  SOURCE="$(echo "$RESOLVED" | jq -r .source)"
fi
```

Branch on `$RESULT`:
- `skip`: accept the derived slug silently — no AskUserQuestion. Emit `askuser_skipped` event with `{question_id: "workflow.slug_confirm", source: "$SOURCE"}`.
<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the slug confirmation question via their native channel. Silent omission is forbidden. -->
- `prefill`: present the AskUserQuestion normally, pre-select the derived slug as the recommended option (label suffix: ` (Recommended — your preference)`). Wrap with `user_wait_start` / `user_wait_end` logging:

  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
    '{"phase":"setup","reason":"slug_confirmation"}'
  _WAIT_T0=$(date +%s%3N)
  # AskUserQuestion(...) with derived slug pre-selected
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
    "$(printf '{"phase":"setup","wall_ms":%d}' "$(( $(date +%s%3N) - _WAIT_T0 ))")"
  ```

- `ask`: if non-obvious, confirm with the user via `AskUserQuestion` normally, wrapped with `user_wait_start` / `user_wait_end` logging (as shown above). If `$SOURCE == "conflict"`, add to the question header: `(Note: config says <X>, memory says <Y> — your answer below will be offered as a conflict-resolution write target.)` After the user picks an answer that differs from both stored values, surface a one-shot follow-up: "Record your answer as the new preference? (config / memory:very_strong / memory:strong / no)".

**Invariant:** the collision check above is a hard safety prerequisite that runs unconditionally regardless of resolver outcome. The resolver only governs the soft non-obvious-slug confirmation gate.

```bash
SLUG="<derived-kebab-slug>"
export Z_HARNESS_SLUG="$SLUG"
```

### Step 2 — Resolve plan dir and RUN id

```bash
Z_HARNESS_PLAN_DIR="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")"
export Z_HARNESS_PLAN_DIR
RUN="$(date -u +%Y%m%dT%H%M%SZ)-$SLUG"
mkdir -p "$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts"
export RUN
```

### Step 3 — Log run start + providers

Capture the z-harness version stamp and log `run_start`:

```bash
VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
START_PAYLOAD="$(python3 -c '
import json, sys
v = json.loads(sys.argv[1]); v["arguments"] = sys.argv[2]
print(json.dumps(v))
' "$VERSION_BLOB" "$ARGUMENTS")"
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_start "$START_PAYLOAD"
```

Log provider resolution once per run (guarded against re-emission):

```bash
if [ ! -f "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged" ]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-providers.sh" || true
  touch "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged"
fi
```

### Step 4 — Notification policy

See [docs/human/config.md](docs/human/config.md) (notify.level key).

### Step 5 — Doc-staleness route check

If `docs/llm/INDEX.json` exists in the repo root, compute staleness across all entries before Phase 0 starts. Read only the lightweight metadata fields (`slug`, `last_updated`, `source_file`). For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`.

Compute `stale_pct = stale_concepts / total_concepts`. Threshold: `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — 20 percent).

If `stale_pct >= threshold`:
- Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md` (artifact for audit trail). Set `ARTIFACT_PATH="$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md"`.
<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the doc-staleness route question (switch to /z-maintain-docs / continue with stale docs / abandon) via their native channel. Silent omission is forbidden. -->
- Log `user_wait_start`, push-notify, and present `AskUserQuestion`: switch to `/z-maintain-docs` / continue here with stale docs / abandon.

  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
    '{"phase":"setup","reason":"docs_staleness_gate"}'
  _WAIT_T0=$(date +%s%3N)
  ```

- Do NOT auto-invoke `/z-maintain-docs`.
- After the user responds, log `user_wait_end` and emit `plan_route_decision` with the resolved `user_choice` populated:

  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
    "$(printf '{"phase":"setup","wall_ms":%d}' "$(( $(date +%s%3N) - _WAIT_T0 ))")"
  ```

  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_route_decision \
    "$(printf '{"from_command":"/z-uplift","to_command":"/z-maintain-docs","route_class":"contextual","reason_codes":["docs_stale"],"signals":{"docs_stale_or_drifted":true},"confidence":"high","classifier_used":false,"artifact_path":"%s","route_chain":["/z-uplift","/z-maintain-docs"],"user_choice":"%s"}' \
       "$ARTIFACT_PATH" "$USER_ROUTE_CHOICE")"
  ```

  Where `USER_ROUTE_CHOICE` is one of `"switch"`, `"continue"`, or `"abandon"` based on the user's response.

- If user chose `"continue"`: emit `doc_drift_acknowledged` event and proceed.
- If user chose `"switch"`: halt with the message "Run `/z-maintain-docs` to refresh docs, then re-invoke `/z-uplift`." Do NOT auto-invoke.
- If user chose `"abandon"`: emit `run_end status: aborted_by_user` and exit.

### Step 6 — Resume detection + flag processing

This step runs after the plan dir and RUN id are resolved (Step 2) and after run_start is logged (Step 3). It handles three scenarios:

1. **`--retry-bailed`**: mutate `[!] bailed:` rows back to `[ ] pending` before resume detection proceeds.
2. **`--refresh-component <name>`**: archive the named component's REPORT.md and TASKS.md, reset its MANIFEST row to `[ ] pending`, then fall through to resume detection.
3. **Resume detection**: if MANIFEST.md exists with at least one row, inspect its states and jump to the appropriate phase; emit `resume_detected` event.

#### Sub-step 6a — Apply `--retry-bailed`

If `RETRY_BAILED=true` and `$Z_HARNESS_PLAN_DIR/MANIFEST.md` exists, change every `[!] bailed:` row to `[ ] pending`:

```bash
if [ "$RETRY_BAILED" = "true" ] && [ -f "$Z_HARNESS_PLAN_DIR/MANIFEST.md" ]; then
  python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" <<'PYEOF'
import re, sys, os

manifest_path = sys.argv[1]
with open(manifest_path) as f:
    content = f.read()

# Replace every bailed-state cell with pending.
# Match the state cell (column 1, between first two pipes) — handles both
# "[ ] bailed" variants and "[!] bailed: <reason>" variants.
updated = re.sub(
    r'(\|)\s*\[!\]\s*bailed:[^\|]*(\|)',
    r'\1 [ ] pending \2',
    content
)
changed = content.count('[!] bailed') - updated.count('[!] bailed')
if changed == 0:
    print("--retry-bailed: no bailed rows found; nothing changed.")
else:
    tmp = manifest_path + ".tmp"
    with open(tmp, "w") as f:
        f.write(updated)
    os.replace(tmp, manifest_path)
    print(f"--retry-bailed: reset {changed} bailed row(s) to pending.")
PYEOF
fi
```

#### Sub-step 6b — Apply `--refresh-component`

If `REFRESH_COMPONENT` is set and `$Z_HARNESS_PLAN_DIR/MANIFEST.md` exists, archive the component's existing artifacts and reset its MANIFEST row to `[ ] pending`:

```bash
if [ -n "$REFRESH_COMPONENT" ] && [ -f "$Z_HARNESS_PLAN_DIR/MANIFEST.md" ]; then
  python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$REFRESH_COMPONENT" \
    "$Z_HARNESS_PLAN_DIR" "$RUN" "$(dirname "$Z_HARNESS_PLAN_DIR")" "$Z_HARNESS_SLUG" <<'PYEOF'
import re, sys, os, shutil

manifest_path  = sys.argv[1]
comp_name      = sys.argv[2]   # the slug passed to --refresh-component
plan_dir       = sys.argv[3]
run            = sys.argv[4]
plans_parent   = sys.argv[5]
uplift_slug    = sys.argv[6]

with open(manifest_path) as f:
    content = f.read()

# Locate the row whose slug column (column 3) matches comp_name.
# Table columns: [0]=empty [1]=state [2]=component [3]=slug [4]=findings [5]=bail [6]=tasks
row_re = re.compile(
    r'^\|[^|\n]*\|[^|\n]*\|\s*' + re.escape(comp_name) + r'\s*\|[^\n]*$',
    re.MULTILINE
)
# MAJOR 5: guard against duplicate rows — assert exactly 1 match before proceeding.
matches = row_re.findall(content)
if len(matches) == 0:
    print(f"ERROR: --refresh-component: no MANIFEST row found for slug '{comp_name}'.")
    sys.exit(1)
if len(matches) > 1:
    print(f"ERROR: --refresh-component: {len(matches)} MANIFEST rows match slug '{comp_name}'; expected exactly 1. MANIFEST not modified.")
    sys.exit(1)

# Resolve the component plan dir: "<plans_parent>/<uplift_slug>-<comp_name>/"
comp_plan_dir = os.path.join(plans_parent, f"{uplift_slug}-{comp_name}")

# MAJOR 4: both source files must exist before any mutation is attempted.
sources = {}
for fname in ("REPORT.md", "TASKS.md"):
    src = os.path.join(comp_plan_dir, fname)
    if not os.path.isfile(src):
        print(f"ERROR: --refresh-component: {fname} not found at {src}. "
              "Both REPORT.md and TASKS.md must exist before archiving. MANIFEST not modified.")
        sys.exit(1)
    sources[fname] = src

# MAJOR 3: atomic archive — stage both files to a tmp directory, verify, then rename into place.
archive_dest = os.path.join(plan_dir, "archive", run, "refreshed", comp_name)
stage_dir    = archive_dest + ".staging"

# Clean any leftover staging dir from a previous interrupted run.
if os.path.exists(stage_dir):
    shutil.rmtree(stage_dir)
os.makedirs(stage_dir, exist_ok=True)

# Copy both files into the staging directory.
for fname, src in sources.items():
    dst = os.path.join(stage_dir, fname)
    shutil.copy2(src, dst)
    if not os.path.isfile(dst):
        print(f"ERROR: staging copy of {fname} failed. MANIFEST not modified.")
        sys.exit(1)

# Atomically rename staging → final archive destination.
os.rename(stage_dir, archive_dest)
print(f"archived {comp_plan_dir}/{{REPORT,TASKS}}.md → {archive_dest}/")

# Remove originals now that archive is confirmed.
for fname, src in sources.items():
    os.remove(src)
    print(f"removed original {src}")

# MAJOR 5: Reset MANIFEST row using replacement_count guard — exactly 1 row must be replaced.
replacement_count = 0

def reset_row(m):
    global replacement_count
    row   = m.group(0)
    cells = row.split('|')
    if len(cells) < 7:
        return row
    cells[1] = ' [ ] pending '
    # Also clear findings, bail, and tasks columns (indices 4, 5, 6)
    cells[4] = ' — '
    cells[5] = ' — '
    cells[6] = ' — '
    replacement_count += 1
    return '|'.join(cells)

updated = row_re.sub(reset_row, content)

if replacement_count != 1:
    print(f"ERROR: --refresh-component: expected to reset exactly 1 MANIFEST row, "
          f"got {replacement_count}. MANIFEST not written.")
    sys.exit(1)

tmp = manifest_path + ".tmp"
with open(tmp, "w") as f:
    f.write(updated)
os.replace(tmp, manifest_path)
print(f"--refresh-component: reset '{comp_name}' row to [ ] pending.")
PYEOF
fi
```

#### Sub-step 6c — Resume detection

If `$Z_HARNESS_PLAN_DIR/MANIFEST.md` exists, inspect MANIFEST state and determine the resume target. Emit `resume_detected` with the detected state, then jump to the appropriate phase. **If no MANIFEST.md exists, skip this step entirely** (fresh run; continue through STYLE.md gate into Phase 0).

```bash
SKIP_TO_PHASE=0
if [ -f "$Z_HARNESS_PLAN_DIR/MANIFEST.md" ]; then
  RESUME_STATE="$(python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" <<'PYEOF'
import re, sys

manifest_path = sys.argv[1]
with open(manifest_path) as f:
    content = f.read()

states = []
for line in content.splitlines():
    line = line.strip()
    if not line.startswith('|') or line.startswith('|---') or line.startswith('| State'):
        continue
    cells = [c.strip() for c in line.split('|')]
    if len(cells) < 7:
        continue
    states.append(cells[1])  # state column

if not states:
    # Empty MANIFEST table — treat as fresh run
    print("fresh")
    sys.exit(0)

# Priority check order (most critical first):
# 1. Any [i] implementing → phase5_implementing
# 2. Any [~] auditing or [ ] pending → phase3_pending
# 3. All rows are [a] audited or terminal ([x]/[s]/[!]) → phase5_ready

has_implementing = any('[i] implementing' in s for s in states)
has_pending_or_auditing = any(
    '[ ] pending' in s or '[~] auditing' in s for s in states
)
all_terminal_or_audited = all(
    '[a] audited' in s or '[x] done' in s or '[s] skipped' in s or '[!] bailed' in s
    for s in states
)

if has_implementing:
    print("phase5_implementing")
elif has_pending_or_auditing:
    print("phase3_pending")
elif all_terminal_or_audited:
    print("phase5_ready")
else:
    # Mixed unknown states — default to phase3 to re-audit
    print("phase3_pending")
PYEOF
)"

  if [ "$RESUME_STATE" != "fresh" ]; then
    # Emit resume_detected event
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" resume_detected \
      "$(printf '{"slug":"%s","manifest_state":"%s"}' "$SLUG" "$RESUME_STATE")"

    case "$RESUME_STATE" in
      phase3_pending)
        # Re-audit: skip Phase 0, Phase 1 (decomposition), Phase 2 (cross-cutting already done).
        # Announce the resume state to the user, then jump directly to Phase 3.
        cat <<RESUME_MSG
RESUME DETECTED — MANIFEST has pending/auditing rows. Resuming at Phase 3 (per-component audits).
  Plan dir : $Z_HARNESS_PLAN_DIR
  MANIFEST : $Z_HARNESS_PLAN_DIR/MANIFEST.md
Skip forward to Phase 3 now. Do NOT re-run Phase 0, Phase 1, or Phase 2.
RESUME_MSG
        # Jump to Phase 3 — skip STYLE.md gate, Phase 0, Phase 1, Phase 2.
        # The STYLE.md gate is re-evaluated inside Phase 3 if needed via $NO_STYLE / $STYLE_MD_PATH
        # which were already initialised from argument parsing.
        SKIP_TO_PHASE=3
        ;;
      phase5_implementing)
        cat <<RESUME_MSG
RESUME DETECTED — MANIFEST has a row in [i] implementing state. Resuming at Phase 5.
  Plan dir : $Z_HARNESS_PLAN_DIR
  MANIFEST : $Z_HARNESS_PLAN_DIR/MANIFEST.md
Skip forward to Phase 5 now. The [i] implementing component will be handled by Step 2a
(interrupted-resume AskUser gate) before the normal [a] audited queue is processed.
RESUME_MSG
        SKIP_TO_PHASE=5
        ;;
      phase5_ready)
        cat <<RESUME_MSG
RESUME DETECTED — All components are [a] audited or terminal. Resuming at Phase 5 (sequential implement).
  Plan dir : $Z_HARNESS_PLAN_DIR
  MANIFEST : $Z_HARNESS_PLAN_DIR/MANIFEST.md
Skip forward to Phase 5 now.
RESUME_MSG
        SKIP_TO_PHASE=5
        ;;
    esac
  fi
fi
```

After setting `SKIP_TO_PHASE`, honor it when entering each phase:

- **STYLE.md gate**: skip entirely if `SKIP_TO_PHASE` is set (the gate ran on the original invocation; no need to re-gate on resume).
- **Phase 0**: skip if `SKIP_TO_PHASE` is set.
- **Phase 1**: skip if `SKIP_TO_PHASE` is set.
- **Phase 2**: skip if `SKIP_TO_PHASE` is set.
- **Phase 3**: skip if `SKIP_TO_PHASE = 5`.
- **Phase 4**: skip if `SKIP_TO_PHASE = 5`.
- **Phase 5**: always run if reached (either normally or via resume).

Check the skip guard at the top of each skippable phase/gate:

```bash
# Example guard — place at the top of each skippable phase.
# Skip phases STRICTLY BEFORE the resume target (e.g. if SKIP_TO_PHASE=3, skip phases 0,1,2 but run 3).
if [ <this-phase-number> -lt "${SKIP_TO_PHASE:-0}" ]; then
  echo "Skipping Phase <N> (resume target is Phase $SKIP_TO_PHASE)"
else
  # ... phase body ...
fi
```

---

## STYLE.md gate

This gate runs immediately after Setup. It is skipped if `NO_STYLE=true`.

Check for STYLE.md:

```bash
if [ "$NO_STYLE" != "true" ]; then
  if ! ls ./STYLE.md >/dev/null 2>&1; then
    # Detection event only — no action field; action is logged per-branch after user responds
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" style_md_missing \
      "$(printf '{"slug":"%s","action":"detected"}' "$SLUG")"
  fi
fi
```

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the missing STYLE.md gate question (run /z-style-init / continue without STYLE / abort) via their native channel. Silent omission is forbidden. -->
If STYLE.md is missing and `NO_STYLE` is not set, log `user_wait_start`, push-notify, and present `AskUserQuestion`:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
  '{"phase":"setup","reason":"style_md_missing_gate"}'
_WAIT_T0=$(date +%s%3N)
```

> No `STYLE.md` found at the repo root. How would you like to proceed?
> 1. Run `/z-style-init` first (recommended) — after it completes, re-invoke `/z-uplift`
> 2. Continue without STYLE.md (cleanliness+design audits degrade to generic rubric) — equivalent to passing `--no-style`
> 3. Abort

After the user responds, log `user_wait_end`:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
  "$(printf '{"phase":"setup","wall_ms":%d}' "$(( $(date +%s%3N) - _WAIT_T0 ))")"
```

Handle the response (emit the outcome-specific event AFTER `user_wait_end` is logged, inside each branch):

- **Option 1** (`/z-style-init`): log the handoff and halt cleanly:

  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" style_init_redirected \
    "$(printf '{"slug":"%s","action":"halted_for_style_init"}' "$SLUG")"
  ```

  Then output the explicit message: "After running `/z-style-init`, re-invoke `/z-uplift` to continue." Do NOT auto-invoke `/z-style-init`.

- **Option 2** (continue without STYLE): set `NO_STYLE=true` and log the continuation:

  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" style_continued_without \
    "$(printf '{"slug":"%s","action":"continued_without_style"}' "$SLUG")"
  ```

- **Option 3** (abort): log run end and exit:

  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_end \
    "$(printf '{"slug":"%s","status":"aborted_by_user","reason":"no_style_md"}' "$SLUG")"
  exit 1
  ```

If STYLE.md is present, note its absolute path for later injection into auditor prompts:

```bash
STYLE_MD_PATH="$(pwd)/STYLE.md"
```

---

## Phase telemetry (mandatory)

At the **start** of each phase (0 through 6), record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If a phase blocks on `AskUserQuestion`, log `user_wait_start` / `user_wait_end` events bracketing the wait.

---

## Phase 0 — Premise check

Record `T0=$(date +%s%3N)` and `USER_WAIT_MS_THIS_PHASE=0` at phase start.

**Do not take the prompt's premises for granted.** Before proceeding with decomposition, verify:

- Does the codebase actually need bulk uplift, or is there a more targeted `/z-audit` call that's more appropriate?
- Are there any obvious blockers (e.g. the repo is a single-file script with no meaningful component boundaries) that would make `/z-uplift` inappropriate?
- Is there a `MANIFEST.md` already present under `$Z_HARNESS_PLAN_DIR/`? If so, this is a resume — describe the current MANIFEST state to the user and confirm whether they want to resume or restart.

If any concern surfaces:

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the premise concern question via their native channel. Silent omission is forbidden. -->
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
  '{"phase":0,"reason":"premise_concern"}'
_WAIT_T0=$(date +%s%3N)
```

Stop and raise it with the user via `AskUserQuestion` before continuing. After the user responds:

```bash
USER_WAIT_MS_THIS_PHASE=$(( USER_WAIT_MS_THIS_PHASE + $(date +%s%3N) - _WAIT_T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
  "$(printf '{"phase":0,"wall_ms":%d}' "$(( $(date +%s%3N) - _WAIT_T0 ))")"
```

If nothing concerning surfaces, write a one-paragraph "premise accepted" summary describing what uplift will cover (component detection strategy, dimensions, STYLE.md status).

Checkpoint: `phase0-premise.md`.

```bash
cp "$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase0-premise.md" 2>/dev/null || true
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":0,"name":"premise-check","wall_ms":%d,"user_wait_ms":%d}' \
     "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

---

## Phase 1 — Decomposition

Record `T0=$(date +%s%3N)` at phase start.

### Step 1 — Resolve components list

If `COMPONENTS_FILE` is set (from `--components=<file>`), read it and build the same `COMPONENTS_JSON` structure that auto-detection produces, then proceed to Step 2 (collision resolution applies to file-supplied components too). `--component <path>` entries are appended afterwards (de-duplicated), so both flags can be combined.

```bash
if [ -n "$COMPONENTS_FILE" ]; then
  COMPONENTS_JSON="$(python3 - "$REPO_ROOT" "$COMPONENTS_FILE" \
    "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' \
       ${EXTRA_COMPONENTS[@]+"${EXTRA_COMPONENTS[@]}"})" <<'PYEOF'
import os, sys, json, re

repo_root    = sys.argv[1]
comp_file    = sys.argv[2]
extra_paths  = json.loads(sys.argv[3])

def to_slug(name):
    s = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return s or name.lower()

def relpath(p):
    return os.path.relpath(p, repo_root)

components = []
seen_paths = set()

with open(comp_file) as fh:
    for raw in fh:
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        rel = relpath(os.path.join(repo_root, line)) if not os.path.isabs(line) else relpath(line)
        if rel not in seen_paths:
            seen_paths.add(rel)
            components.append({"path": rel, "method": "manual-file"})

# Append --component <path> extras (de-duplicated)
for ep in extra_paths:
    rel = relpath(os.path.join(repo_root, ep)) if not os.path.isabs(ep) else relpath(ep)
    if rel not in seen_paths:
        seen_paths.add(rel)
        components.append({"path": rel, "method": "manual"})

for c in components:
    c["slug"] = to_slug(os.path.basename(c["path"]))
    c["unclaimed"] = False

print(json.dumps({"components": components, "unclaimed": []}))
PYEOF
)"
fi
```

If `COMPONENTS_FILE` was set, skip the auto-detection block below and jump to Step 2.

Otherwise run auto-detection via inline Python:

```python
#!/usr/bin/env python3
import os, sys, json, re

repo_root = sys.argv[1]
extra_components = json.loads(sys.argv[2])  # list of paths from --component flags

DENYLIST = {
    "docs", "target", "node_modules", "dist", "build",
    ".git", "z-harness", "__pycache__", ".venv",
}

MANIFEST_FILES = ["Cargo.toml", "pyproject.toml", "setup.cfg", "package.json"]

def to_slug(name):
    """Kebab-case slug: basename lowercased, non-alnum runs replaced with '-', strip leading/trailing '-'."""
    s = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return s or name.lower()

def relpath(p):
    return os.path.relpath(p, repo_root)

# Cross-method de-duplication: path-keyed dict, first-seen method wins.
# Iteration order is cargo → pyproject → setup.cfg → package.json.
detected_by_path = {}  # rel_path -> method

# Step 1a — Cargo workspace
cargo_toml = os.path.join(repo_root, "Cargo.toml")
if os.path.isfile(cargo_toml):
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with open(cargo_toml, "rb") as f:
        cargo = tomllib.load(f)
    members = cargo.get("workspace", {}).get("members", [])
    import glob as _glob
    for pattern in members:
        for match in _glob.glob(os.path.join(repo_root, pattern)):
            if os.path.isdir(match):
                rel = relpath(match)
                if rel not in detected_by_path:
                    detected_by_path[rel] = "cargo-workspace"

# Step 1b — pyproject.toml (tool.poetry.packages and project.packages)
pyproject_toml = os.path.join(repo_root, "pyproject.toml")
if os.path.isfile(pyproject_toml):
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with open(pyproject_toml, "rb") as f:
        pyproject = tomllib.load(f)
    poetry_pkgs = pyproject.get("tool", {}).get("poetry", {}).get("packages", [])
    for pkg in poetry_pkgs:
        if isinstance(pkg, dict):
            include = pkg.get("include", "")
            from_dir = pkg.get("from", "")
            path_str = os.path.join(from_dir, include) if from_dir else include
        else:
            path_str = str(pkg)
        if path_str:
            p = os.path.join(repo_root, path_str)
            if os.path.isdir(p):
                rel = relpath(p)
                if rel not in detected_by_path:
                    detected_by_path[rel] = "pyproject"
    project_pkgs = pyproject.get("project", {}).get("packages", [])
    for pkg in project_pkgs:
        if isinstance(pkg, dict):
            include = pkg.get("include", "")
            from_dir = pkg.get("from", "")
            path_str = os.path.join(from_dir, include) if from_dir else include
        else:
            path_str = str(pkg)
        if path_str:
            p = os.path.join(repo_root, path_str)
            if os.path.isdir(p):
                rel = relpath(p)
                if rel not in detected_by_path:
                    detected_by_path[rel] = "pyproject"

# Step 1c — setup.cfg [options] packages
setup_cfg = os.path.join(repo_root, "setup.cfg")
if os.path.isfile(setup_cfg):
    import configparser
    cfg = configparser.ConfigParser()
    cfg.read(setup_cfg)
    raw = cfg.get("options", "packages", fallback="").strip()
    if raw == "find:":
        # Standard setuptools find: — scan [options.packages.find] where (default ".")
        where = cfg.get("options.packages.find", "where", fallback=".").strip()
        scan_root = os.path.join(repo_root, where)
        try:
            for entry in sorted(os.listdir(scan_root)):
                full = os.path.join(scan_root, entry)
                if os.path.isdir(full) and os.path.isfile(os.path.join(full, "__init__.py")):
                    rel = relpath(full)
                    if rel not in detected_by_path:
                        detected_by_path[rel] = "setup.cfg"
        except OSError:
            pass
    else:
        for pkg in raw.split():
            pkg = pkg.strip().rstrip(",")
            if pkg and pkg != "find:":
                p = os.path.join(repo_root, pkg.replace(".", os.sep))
                if os.path.isdir(p):
                    rel = relpath(p)
                    if rel not in detected_by_path:
                        detected_by_path[rel] = "setup.cfg"

# Step 1d — package.json workspaces
pkg_json = os.path.join(repo_root, "package.json")
if os.path.isfile(pkg_json):
    import json as _json
    with open(pkg_json) as f:
        pkg = _json.load(f)
    ws = pkg.get("workspaces", [])
    if isinstance(ws, dict):
        ws = ws.get("packages", [])
    import glob as _glob
    for pattern in ws:
        for match in _glob.glob(os.path.join(repo_root, pattern)):
            if os.path.isdir(match):
                rel = relpath(match)
                if rel not in detected_by_path:
                    detected_by_path[rel] = "npm-workspaces"

# Build components list from de-duped dict
components = [{"path": p, "method": m} for p, m in detected_by_path.items()]

# Precompute whether any manifest file exists — controls fallback vs unclaimed behaviour
MANIFEST_EXISTS = any(
    os.path.isfile(os.path.join(repo_root, mf)) for mf in MANIFEST_FILES
)

# Step 1e — top-level non-hidden dirs minus denylist (fallback)
claimed_paths = set(c["path"] for c in components)
fallback = []
unclaimed = []
try:
    entries = os.listdir(repo_root)
except OSError:
    entries = []
for entry in sorted(entries):
    if entry.startswith("."):
        continue
    if entry in DENYLIST:
        continue
    full = os.path.join(repo_root, entry)
    if not os.path.isdir(full):
        continue
    rel = relpath(full)
    if rel not in claimed_paths:
        fallback.append({"path": rel, "method": "top-level-fallback"})

if not MANIFEST_EXISTS:
    # No manifest file at root: use fallback dirs as components (no unclaimed list)
    components.extend(fallback)
else:
    # Manifest file exists but some dirs aren't covered → report as unclaimed
    all_claimed = set(c["path"] for c in components)
    for item in fallback:
        if item["path"] not in all_claimed:
            unclaimed.append(item["path"])

# Step 1f — append --component <path> extras AFTER unclaimed computation
# so manual entries don't pollute the unclaimed set
manual_paths = set()
for extra_path in extra_components:
    rel = relpath(os.path.join(repo_root, extra_path)) if not os.path.isabs(extra_path) else relpath(extra_path)
    manual_paths.add(rel)
    if rel not in set(c["path"] for c in components):
        components.append({"path": rel, "method": "manual"})

# Re-filter unclaimed: remove any path that was explicitly added via --component
unclaimed = [u for u in unclaimed if u not in manual_paths]

# Compute slugs
for c in components:
    c["slug"] = to_slug(os.path.basename(c["path"]))
    c["unclaimed"] = False

result = {
    "components": components,
    "unclaimed": unclaimed,
}
print(json.dumps(result))
```

Run the script (emit the Python block above as a heredoc and capture its JSON output):

```bash
COMPONENTS_JSON="$(python3 - "$REPO_ROOT" \
  "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' \
     ${EXTRA_COMPONENTS[@]+"${EXTRA_COMPONENTS[@]}"})" <<'PYEOF'
<paste the inline Python script block above here verbatim>
PYEOF
)"
```

### Step 2 — Slug collision detection and disambiguation

Detect collisions and present one `AskUserQuestion` per colliding slug. Apply the user's choice to mutate `COMPONENTS_JSON` before writing COMPONENTS.md (Steps 3–6 consume the resolved JSON).

```bash
COMPONENTS_JSON="$(python3 - "$COMPONENTS_JSON" <<'PYEOF'
import json, sys

data = json.loads(sys.argv[1])
components = data["components"]

def find_collisions(comps):
    from collections import defaultdict
    groups = defaultdict(list)
    for c in comps:
        groups[c["slug"]].append(c)
    return {slug: cs for slug, cs in groups.items() if len(cs) > 1}

collisions = find_collisions(components)
# Process collision slugs in alphabetical order for determinism
for slug in sorted(collisions.keys()):
    colliding = sorted(collisions[slug], key=lambda c: c["path"])
    # Build AskUserQuestion prompt text and print it (orchestrator calls AskUserQuestion)
    lines = [
        f"COLLISION: Two components share the slug `{slug}`:",
        f"  A: {colliding[0]['path']}",
        f"  B: {colliding[1]['path']}",
        "Options:",
        f"  1. Keep `{slug}` for A ({colliding[0]['path']}), rename B to `{slug}-2`",
        f"  2. Keep `{slug}` for B ({colliding[1]['path']}), rename A to `{slug}-1`",
        f"  3. Enter custom slugs for both (format: <slug-A> <slug-B>)",
    ]
    print("\n".join(lines), file=sys.stderr)

# Output unchanged JSON — orchestrator calls AskUserQuestion using the COLLISION lines
# above, receives user response, then runs the apply-choice pass below.
print(json.dumps(data))
PYEOF
)"
```

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface each slug collision disambiguation question via their native channel. Silent omission is forbidden. -->
For each `COLLISION:` block printed above, log `user_wait_start`, call `AskUserQuestion` with the offered options, log `user_wait_end`, then apply the choice:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
  '{"phase":1,"reason":"slug_collision_disambiguation"}'
_WAIT_T0=$(date +%s%3N)
# AskUserQuestion(...)
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
  "$(printf '{"phase":1,"wall_ms":%d}' "$(( $(date +%s%3N) - _WAIT_T0 ))")"
USER_WAIT_MS_THIS_PHASE=$(( USER_WAIT_MS_THIS_PHASE + $(date +%s%3N) - _WAIT_T0 ))
```

```bash
# Apply collision resolution choices.
# Runs in a while-loop until the slug list is collision-free (handles N-way collisions
# and the case where a user-supplied custom slug introduces a new collision).
# A no-progress sanity counter (fires after 3 stalled iterations) prevents infinite loops.
COMPONENTS_JSON="$(python3 - "$COMPONENTS_JSON" "$USER_COLLISION_CHOICES" <<'PYEOF'
import json, re, sys
from collections import defaultdict

SLUG_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')

data   = json.loads(sys.argv[1])
# USER_COLLISION_CHOICES is a JSON array of {"slug": str, "choice": str} objects
choices = json.loads(sys.argv[2]) if sys.argv[2] else []
choice_map = {ch["slug"]: ch["choice"] for ch in choices}

components = data["components"]

def find_collisions(comps):
    groups = defaultdict(list)
    for c in comps:
        groups[c["slug"]].append(c)
    return {slug: cs for slug, cs in groups.items() if len(cs) > 1}

prev_collision_count = -1
sanity = 0
while True:
    collisions = find_collisions(components)
    if not collisions:
        break
    if len(collisions) == prev_collision_count:
        sanity += 1
        if sanity > 3:
            print(f"ERROR: collision resolution made no progress over 3 iterations — aborting. Stuck slugs: {sorted(collisions.keys())}", file=sys.stderr)
            sys.exit(1)
    else:
        sanity = 0
    prev_collision_count = len(collisions)
    for slug in sorted(collisions.keys()):
        colliding = sorted(collisions[slug], key=lambda c: c["path"])
        choice = choice_map.get(slug, "1")
        if choice == "1":
            # A keeps slug; B gets slug-2
            colliding[1]["slug"] = slug + "-2"
        elif choice == "2":
            # B keeps slug; A gets slug-1
            colliding[0]["slug"] = slug + "-1"
        else:
            # Custom: "slug-A slug-B" — validate each against slug regex before applying
            parts = choice.strip().split()
            if len(parts) >= 2:
                for i, part in enumerate(parts[:2]):
                    if not SLUG_RE.match(part):
                        print(f"ERROR: custom slug '{part}' is invalid — must match ^[a-z0-9]+(?:-[a-z0-9]+)*$. Aborting.", file=sys.stderr)
                        sys.exit(1)
                colliding[0]["slug"] = parts[0]
                colliding[1]["slug"] = parts[1]

# Final re-check: verify no duplicates were introduced by custom choices
remaining = find_collisions(components)
if remaining:
    print(f"ERROR: slug collision introduced by custom choice: {sorted(remaining.keys())}. Re-run with corrected slugs.", file=sys.stderr)
    sys.exit(1)

data["components"] = components
print(json.dumps(data))
PYEOF
)"
```

Set `USER_COLLISION_CHOICES` to the JSON array of user responses collected from `AskUserQuestion` calls above (one entry per colliding slug). If there are no collisions, set `USER_COLLISION_CHOICES='[]'` and the block is a no-op.

**This collision-resolution block runs before writing COMPONENTS.md.**

### Step 3 — Write COMPONENTS.md

```bash
python3 - "$Z_HARNESS_PLAN_DIR" "$COMPONENTS_JSON" <<'PYEOF'
import json, sys, os

plan_dir = sys.argv[1]
data = json.loads(sys.argv[2])
components = data["components"]
unclaimed = data.get("unclaimed", [])

lines = []
lines.append("# Components detected — " + os.environ.get("SLUG", "uplift") + "\n")
lines.append("| Component | Path | Detection method | Slug |")
lines.append("|-----------|------|------------------|------|")
for c in components:
    lines.append(f"| {c['path']} | {c['path']} | {c['method']} | {c['slug']} |")
lines.append("")
if unclaimed:
    lines.append("## Unclaimed (not covered by any detection method)")
    for u in unclaimed:
        lines.append(f"- {u}/")
    lines.append("")
lines.append("To exclude a component: edit this file and remove its row before confirming.")
lines.append("To include an unclaimed dir: move its bullet into the table with method=`manual`.")

os.makedirs(plan_dir, exist_ok=True)
with open(os.path.join(plan_dir, "COMPONENTS.md"), "w") as f:
    f.write("\n".join(lines) + "\n")
print("wrote COMPONENTS.md")
PYEOF
```

### Step 4 — Emit component_detected telemetry

For each component in the resolved list (after collision resolution), emit one `component_detected` event:

```bash
# Emit per-component telemetry
python3 - "$RUN" "$COMPONENTS_JSON" <<'PYEOF'
import json, sys, subprocess, os

run = sys.argv[1]
data = json.loads(sys.argv[2])
script = os.environ.get("ANTIGRAVITY_PLUGIN_ROOT", os.environ.get("CLAUDE_PLUGIN_ROOT", "")) + "/scripts/log-event.sh"
for c in data["components"]:
    payload = json.dumps({"slug": c["slug"], "path": c["path"], "method": c["method"], "unclaimed": c.get("unclaimed", False)})
    result = subprocess.run(["bash", script, run, "component_detected", payload])
    if result.returncode != 0:
        print(f"WARNING: component_detected telemetry failed for {c['slug']} (exit {result.returncode}); continuing.", file=sys.stderr)
PYEOF
```

### Step 5 — Push-notify + AskUser gate

Push-notify the user that decomposition is ready.

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the decomposition confirm question (proceed / abort) via their native channel. Silent omission is forbidden. -->
Log `user_wait_start`, present `AskUserQuestion`, then log `user_wait_end`:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
  '{"phase":1,"reason":"decomposition_confirm"}'
_WAIT_T0=$(date +%s%3N)
```

> Decomposition complete. Review `$Z_HARNESS_PLAN_DIR/COMPONENTS.md` — it lists N component(s) detected via [methods].
>
> How would you like to proceed?
> 1. Proceed — confirm the detected components and continue to Phase 2
> 2. Abort — to revise the decomposition, edit `COMPONENTS.md` (or re-invoke with `--components=<file>` / `--component <path>`), then re-invoke `/z-uplift`

```bash
USER_WAIT_MS_THIS_PHASE=$(( USER_WAIT_MS_THIS_PHASE + $(date +%s%3N) - _WAIT_T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
  "$(printf '{"phase":1,"wall_ms":%d}' "$(( $(date +%s%3N) - _WAIT_T0 ))")"
```

If the user chooses **Abort**: emit `run_end status: aborted_by_user` and exit. Do NOT offer an "edit in-place" loop.

If the user chooses **Proceed**: continue to Step 6.

### Step 6 — Initialize MANIFEST.md

Write `$Z_HARNESS_PLAN_DIR/MANIFEST.md` with all confirmed components in `[ ] pending` state:

```bash
python3 - "$Z_HARNESS_PLAN_DIR" "$COMPONENTS_JSON" "$SLUG" "$RUN" <<'PYEOF'
import json, sys, os
from datetime import datetime, timezone

plan_dir, data_str, slug, run = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
data = json.loads(data_str)
components = data["components"]

lines = [
    f"# Uplift MANIFEST — {slug}",
    "",
    f"Generated: {datetime.now(timezone.utc).isoformat()}",
    f"Run: {run}",
    f"Detection: {'manual' if all(c['method']=='manual' for c in components) else 'auto' if all(c['method']!='manual' for c in components) else 'mixed'}",
    "",
    "| State | Component | Slug | Audit findings | Bail reason | TASKS.md |",
    "|-------|-----------|------|----------------|-------------|----------|",
]
for c in components:
    lines.append(f"| [ ] pending | {c['path']} | {c['slug']} | — | — | — |")
lines.append("")

with open(os.path.join(plan_dir, "MANIFEST.md"), "w") as f:
    f.write("\n".join(lines) + "\n")
print("wrote MANIFEST.md")
PYEOF
```

### Step 7 — Phase 1 checkpoint

Write checkpoint and log phase end:

```bash
cp "$Z_HARNESS_PLAN_DIR/COMPONENTS.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase1-decomposition.md"
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":1,"name":"decomposition","wall_ms":%d,"user_wait_ms":%d}' \
     "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

---

## Phase 2 — Cross-cutting pass

Record `T0=$(date +%s%3N)` at phase start.

If `CROSS_CUTTING_SKIP=true`:

```bash
cat > "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" <<'EOF'
# Cross-cutting findings — (skipped)

Cross-cutting pass was skipped via --cross-cutting=skip.
EOF
cp "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase2-cross-cutting.md"
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":2,"name":"cross-cutting","wall_ms":%d,"user_wait_ms":0,"skipped":true}' "$WALL_MS")"
```

**STOP — do not execute Steps 1-7 below if `CROSS_CUTTING_SKIP=true`. Steps 1-7 apply only when `CROSS_CUTTING_SKIP=false`.**

Otherwise (`CROSS_CUTTING_SKIP=false`), execute Steps 1-7 below:

### Step 1 — Build source map

Curate a source map of up to ~100 paths: the top-50 files by churn over the last 90 days (filtered to paths that still exist on disk), UNION the entry file for each component.

```bash
SOURCE_MAP_JSON="$(python3 - "$Z_HARNESS_PLAN_DIR" "$COMPONENTS_JSON" "$(pwd)" <<'PYEOF'
import os, sys, json, subprocess

plan_dir     = sys.argv[1]
data         = json.loads(sys.argv[2])
repo_root    = sys.argv[3]
components   = data["components"]

# --- churn top-50 (paths still present on disk) ---
result = subprocess.run(
    ["git", "log", "--since=90 days ago", "--name-only", "--format="],
    capture_output=True, text=True, cwd=repo_root
)
from collections import Counter
counts = Counter()
for line in result.stdout.splitlines():
    line = line.strip()
    if line:
        counts[line] += 1

churn_paths = []
for path, _ in counts.most_common(200):
    abs_path = os.path.join(repo_root, path)
    if os.path.isfile(abs_path):
        churn_paths.append(path)
    if len(churn_paths) >= 50:
        break

# --- entry-file heuristic per component ---
def entry_file(comp_path, repo_root):
    """Return relative path of entry file for this component (first match wins)."""
    abs_comp = os.path.join(repo_root, comp_path) if not os.path.isabs(comp_path) else comp_path
    candidates = [
        os.path.join(abs_comp, "README.md"),
        os.path.join(abs_comp, "src", "lib.rs"),
        os.path.join(abs_comp, "src", "main.rs"),
        os.path.join(abs_comp, "__init__.py"),
        os.path.join(abs_comp, "package.json"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return os.path.relpath(c, repo_root)
    # first non-test source file lexicographically (up to 2 levels deep, source extensions only)
    SOURCE_EXTS = {
        ".py", ".rs", ".go", ".ts", ".tsx", ".js", ".jsx",
        ".java", ".kt", ".swift", ".cpp", ".c", ".h", ".hpp", ".rb",
    }
    try:
        candidates_src = []
        for depth, (dirpath, dirnames, filenames) in enumerate(os.walk(abs_comp)):
            # Limit recursion to 2 levels deep
            rel_depth = dirpath[len(abs_comp):].count(os.sep)
            if rel_depth >= 2:
                dirnames.clear()
                continue
            # Exclude test dirs and pycache in-place so os.walk doesn't descend
            dirnames[:] = [
                d for d in sorted(dirnames)
                if "test" not in d.lower() and d != "__pycache__"
            ]
            for fname in sorted(filenames):
                if "test" in fname.lower():
                    continue
                _, ext = os.path.splitext(fname)
                if ext not in SOURCE_EXTS:
                    continue
                full = os.path.join(dirpath, fname)
                candidates_src.append(full)
        if candidates_src:
            return os.path.relpath(candidates_src[0], repo_root)
    except OSError:
        pass
    # final fallback: component root path itself (directory)
    return comp_path

entry_paths = []
for c in components:
    ep = entry_file(c["path"], repo_root)
    if ep:
        abs_ep = os.path.join(repo_root, ep)
        if os.path.isfile(abs_ep) or os.path.isdir(abs_ep):
            entry_paths.append(ep)

# merge, de-duplicate, cap at ~100
seen = set()
merged = []
for p in churn_paths + entry_paths:
    if p not in seen:
        seen.add(p)
        merged.append(p)
    if len(merged) >= 100:
        break

print(json.dumps(merged))
PYEOF
)"
```

### Step 2 — Load STYLE.md content (if applicable)

```bash
if [ "$NO_STYLE" != "true" ] && [ -f "$STYLE_MD_PATH" ]; then
  STYLE_CONTENT="$(cat "$STYLE_MD_PATH")"
else
  STYLE_CONTENT=""
fi
```

### Step 3 — Build prompt body

```bash
COMPONENTS_MD_CONTENT="$(cat "$Z_HARNESS_PLAN_DIR/COMPONENTS.md")"
SOURCE_MAP_PATHS="$(python3 -c 'import json,sys; paths=json.loads(sys.argv[1]); print("\n".join(paths))' "$SOURCE_MAP_JSON")"

CROSS_CUTTING_PROMPT="MODE: cross-cutting-uplift

repo_root: $(pwd)
slug: $SLUG

components:
$COMPONENTS_MD_CONTENT

source_map (files to examine — top-50 by churn over last 90 days plus component entry files):
$SOURCE_MAP_PATHS
$([ -n "$STYLE_CONTENT" ] && printf '\nSTYLE.md:\n%s\n' "$STYLE_CONTENT" || true)
Instructions: Examine the source map files for cross-component issues. For each finding, emit an explicit \`component: <slug-from-MANIFEST>\` marker (use the exact slug from the components table, or \`component: global\` for issues spanning all components). Then classify each finding as one of:
- \`global-task\` — cross-component issues requiring a dedicated plan (duplicated abstractions, global API drift, cross-cutting architectural debt)
- \`per-component-context\` — issues that should inform the per-component audit for that specific component
- \`risk\` — watch items with no immediately actionable fix

Style-drift findings must cite STYLE rule IDs explicitly.
Number global-task findings G-001, G-002, ... (include affected files). Number per-component-context findings C-001, C-002, .... Number risk findings R-001, R-002, ....

CRITICAL FORMAT REQUIREMENT: Each finding MUST be a bullet beginning with \`G-NNN\`, \`C-NNN\`, or \`R-NNN\` (e.g. \`- G-001 ...\`). The orchestrator's parser will silently drop any bullet that does not match this exact pattern."
```

### Step 4 — Dispatch consultants in parallel

Dispatch `consultant-primary` and `consultant-secondary` in a single message (two `Agent(...)` calls):

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this parallel cross-cutting consultant dispatch requirement to the user and skip the Agent() calls. The cross-cutting pass is required to detect repo-wide issues; drivers that skip it must warn the user that cross-cutting analysis has been bypassed. -->
```
Agent(
  subagent_type="consultant-primary",
  description="Cross-cutting uplift (primary) for <slug>",
  prompt="<CROSS_CUTTING_PROMPT>"
)
Agent(
  subagent_type="consultant-secondary",
  description="Cross-cutting uplift (secondary) for <slug>",
  prompt="<CROSS_CUTTING_PROMPT>"
)
```

Archive both transcripts:

```bash
echo "$PRIMARY_TRANSCRIPT"   > "$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts/phase2-consultant-primary.md"
echo "$SECONDARY_TRANSCRIPT" > "$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts/phase2-consultant-secondary.md"
```

### Step 5 — Merge findings into CROSS-CUTTING.md

Run the following deterministic merge script. It reads both consultant transcripts, extracts each finding by its `component:` marker, normalizes into the three sections, defaults missing `class:` to `per-component-context`, and drops any finding without a `component:` marker (with a warning):

```bash
python3 - \
  "$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts/phase2-consultant-primary.md" \
  "$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts/phase2-consultant-secondary.md" \
  "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" \
  "$SLUG" <<'PYEOF'
import re, sys

primary_path   = sys.argv[1]
secondary_path = sys.argv[2]
out_path       = sys.argv[3]
slug           = sys.argv[4]

def read_safe(path):
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return ""

def extract_findings(text):
    """
    Parse consultant transcript into a list of finding dicts.
    Each finding block is delimited by lines starting with a numbered prefix
    (G-NNN, C-NNN, R-NNN) or a markdown bullet. Fields recognised:
      component: <slug>
      class: global-task | per-component-context | risk
      files: <comma-separated list>
      subject: <free text>
    The finding text up to the next delimiter becomes the body.
    """
    findings = []
    # Split on bullet lines that start a finding number
    blocks = re.split(r'(?=^[-*]\s+(?:G|C|R)-\d+)', text, flags=re.MULTILINE)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        # Detect finding type from prefix
        type_match = re.match(r'^[-*]\s+(G|C|R)-(\d+)', block)
        if not type_match:
            continue
        prefix   = type_match.group(1)  # G / C / R
        num_str  = type_match.group(2)

        # Parse key: value fields
        fields = {}
        for key in ("component", "class", "files", "subject"):
            m = re.search(rf'(?:^|\s){re.escape(key)}:\s*(.+?)(?:\n|$)', block, re.IGNORECASE | re.MULTILINE)
            if m:
                fields[key] = m.group(1).strip()

        # Default class from prefix if not explicitly set
        if "class" not in fields:
            if prefix == "G":
                fields["class"] = "global-task"
            elif prefix == "R":
                fields["class"] = "risk"
            else:
                fields["class"] = "per-component-context"

        # Drop findings missing component: marker (warn to stderr)
        if "component" not in fields:
            print(f"WARNING: finding {prefix}-{num_str} has no component: marker — dropped", file=sys.stderr)
            continue

        # Build subject from first non-field line if not explicitly set
        if "subject" not in fields:
            first_line = block.splitlines()[0] if block.splitlines() else ""
            # Strip the G/C/R-NNN prefix and leading punctuation
            subj = re.sub(r'^[-*]\s+[GCR]-\d+\s*[—\-]+\s*(?:\[[^\]]+\]\s*)?', '', first_line).strip()
            fields["subject"] = subj or first_line

        fields["_prefix"] = prefix
        fields["_num"]    = int(num_str)
        fields["_block"]  = block
        findings.append(fields)

    return findings

primary_text   = read_safe(primary_path)
secondary_text = read_safe(secondary_path)

primary_findings   = extract_findings(primary_text)
secondary_findings = extract_findings(secondary_text)

# De-duplicate: key by (component, normalised subject). Primary findings win.
def norm(s):
    return re.sub(r'\s+', ' ', s.lower().strip())

seen_keys = set()
merged = []
for f in primary_findings + secondary_findings:
    key = (f.get("component", ""), norm(f.get("subject", "")))
    if key not in seen_keys:
        seen_keys.add(key)
        merged.append(f)

# Normalise class values
CLASS_MAP = {
    "global-task":           "global-task",
    "global_task":           "global-task",
    "global":                "global-task",
    "per-component-context": "per-component-context",
    "per_component_context": "per-component-context",
    "per-component":         "per-component-context",
    "context":               "per-component-context",
    "risk":                  "risk",
}

def normalise_class(raw):
    return CLASS_MAP.get(raw.lower().replace(" ", "-"), "per-component-context")

for f in merged:
    f["class"] = normalise_class(f.get("class", ""))

# Warn about bullets that looked like findings but were not matched by the strict G/C/R-NNN parser.
# Counts candidate bullets (any "- <word>" line) across both transcripts, compares against
# the number actually parsed, and emits a warning + telemetry event if any were dropped.
combined_text = primary_text + "\n" + secondary_text
candidate_bullets = re.findall(r'^\s*[-*]\s+\S+', combined_text, re.MULTILINE)
strict_matched = len(primary_findings) + len(secondary_findings)
dropped = max(0, len(candidate_bullets) - strict_matched)
if dropped > 0:
    import subprocess as _sp, json as _json, os as _os
    _plugin_root = _os.environ.get("ANTIGRAVITY_PLUGIN_ROOT", _os.environ.get("CLAUDE_PLUGIN_ROOT", ""))
    _run = _os.environ.get("RUN", "uplift")
    _sp.run(["bash", _plugin_root + "/scripts/log-event.sh", _run,
             "cross_cutting_findings_dropped",
             _json.dumps({"slug": slug, "count": dropped})],
            check=False)
    print(f"WARNING: {dropped} bullet(s) in cross-cutting output did not match G-NNN/C-NNN/R-NNN pattern and were dropped.")

# Sort into buckets and assign sequential numbers
global_tasks   = [f for f in merged if f["class"] == "global-task"]
per_comp       = [f for f in merged if f["class"] == "per-component-context"]
risks          = [f for f in merged if f["class"] == "risk"]

lines = [f"# Cross-cutting findings — {slug}", ""]

lines.append("## Global tasks (need dedicated plan)")
for i, f in enumerate(global_tasks, 1):
    gnum    = f"G-{i:03d}"
    subject = f.get("subject", "(no subject)")
    comp    = f.get("component", "global")
    files   = f.get("files", "")
    entry   = f"- {gnum} — {subject} — component: {comp}"
    if files:
        entry += f" — files: {files}"
    lines.append(entry)
lines.append("")

lines.append("## Per-component context (inform audits)")
for i, f in enumerate(per_comp, 1):
    cnum    = f"C-{i:03d}"
    comp    = f.get("component", "global")
    subject = f.get("subject", "(no subject)")
    lines.append(f"- {cnum} — component: {comp} — {subject}")
lines.append("")

lines.append("## Risks (watch items)")
for i, f in enumerate(risks, 1):
    rnum    = f"R-{i:03d}"
    comp    = f.get("component", "global")
    subject = f.get("subject", "(no subject)")
    lines.append(f"- {rnum} — component: {comp} — {subject}")
lines.append("")

with open(out_path, "w") as fh:
    fh.write("\n".join(lines))

print(f"wrote {out_path}: {len(global_tasks)} global-tasks, {len(per_comp)} per-component-context, {len(risks)} risks")
PYEOF
```

Compute `G_COUNT`, `C_COUNT`, and `R_COUNT` immediately after CROSS-CUTTING.md is written — before the Step 6 if-check:

```bash
G_COUNT="$(python3 -c "
import re
with open('$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md') as fh:
    content = fh.read()
print(len(re.findall(r'^- G-\d+', content, re.MULTILINE)))
")"
C_COUNT="$(python3 -c "
import re
with open('$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md') as fh:
    content = fh.read()
print(len(re.findall(r'^- C-\d+', content, re.MULTILINE)))
")"
R_COUNT="$(python3 -c "
import re
with open('$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md') as fh:
    content = fh.read()
print(len(re.findall(r'^- R-\d+', content, re.MULTILINE)))
")"
```

### Step 6 — Create synthetic cross-cutting plan (if global-task count > 0)

`G_COUNT` was computed at the end of Step 5. If `G_COUNT > 0`:

```bash
CROSS_DIR="$(dirname "$Z_HARNESS_PLAN_DIR")/${Z_HARNESS_SLUG}-cross-cutting"
mkdir -p "$CROSS_DIR"
```

Write `$CROSS_DIR/SPEC.md`:

```markdown
# Spec — <slug>-cross-cutting

This synthetic component addresses global-task findings from the cross-cutting pass.

See: <abs path to CROSS-CUTTING.md>
```

Write `$CROSS_DIR/PLAN.md`:

```markdown
# Plan — <slug>-cross-cutting

Implement each global-task finding (G-001, G-002, ...) as a separate task.
Findings are sourced from CROSS-CUTTING.md.
```

Generate `$CROSS_DIR/TASKS.md` — one task per G-NNN entry. Parse the G-NNN lines from CROSS-CUTTING.md to extract the subject and affected files:

```bash
python3 - "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" "$CROSS_DIR/TASKS.md" "$Z_HARNESS_PLAN_DIR" <<'PYEOF'
import re, sys

cc_path   = sys.argv[1]
tasks_out = sys.argv[2]
plan_dir  = sys.argv[3]

with open(cc_path) as f:
    content = f.read()

# Extract G-NNN lines from the Global tasks section
global_section = re.search(
    r'## Global tasks.*?\n(.*?)(?=\n## |\Z)', content, re.DOTALL
)
tasks_lines = []
if global_section:
    for line in global_section.group(1).splitlines():
        line = line.strip()
        if not line.startswith('-'):
            continue
        # Parse each finding line-by-line into a field dict, independent of field order
        fields = {}
        # Extract the finding number first
        num_match = re.match(r'-\s+(G-\d+)', line)
        if not num_match:
            continue
        gnum = num_match.group(1)
        # Parse all key: value pairs by scanning each dash-separated segment
        for segment in re.split(r'\s+[—\-]+\s+', line):
            for key in ("component", "files", "subject", "class"):
                kv = re.match(rf'{re.escape(key)}:\s*(.+)', segment.strip(), re.IGNORECASE)
                if kv:
                    fields[key] = kv.group(1).strip()
        # If subject not found as a key:value, infer from the segment after the gnum
        if "subject" not in fields:
            # Remove the leading "- G-NNN" and take the next segment
            after_num = re.sub(r'^-\s+G-\d+\s*[—\-]*\s*', '', line).strip()
            # Strip severity tag like [HIGH]
            after_num = re.sub(r'^\[[^\]]+\]\s*', '', after_num)
            # Remove any trailing component/files fields
            after_num = re.split(r'\s+[—\-]+\s+(?:component|files?):', after_num, flags=re.IGNORECASE)[0]
            fields["subject"] = after_num.strip() or line

        subject    = fields.get("subject", line)
        files      = fields.get("files", "")
        files_line = f"  - {files}" if files else "  - (see CROSS-CUTTING.md)"
        tasks_lines.append(
            f"### [{gnum}] {subject}\n"
            f"- **Files:**\n{files_line}\n"
            f"- **Depends on:** (none)\n"
            f"- **Acceptance:** Resolve the cross-cutting issue described in {plan_dir}/CROSS-CUTTING.md#{gnum}.\n"
        )

header = "# Tasks — cross-cutting global tasks\n\nGenerated from CROSS-CUTTING.md global-task findings.\n\n"
with open(tasks_out, "w") as f:
    f.write(header + "\n".join(tasks_lines) + "\n")
print(f"wrote {tasks_out} with {len(tasks_lines)} task(s)")
PYEOF
```

Insert `<slug>-cross-cutting` as the FIRST row in MANIFEST.md:

```bash
python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_SLUG" "$CROSS_DIR" <<'PYEOF'
import sys, re

manifest_path = sys.argv[1]
slug          = sys.argv[2]
cross_dir     = sys.argv[3]

with open(manifest_path) as f:
    content = f.read()

cross_slug = f"{slug}-cross-cutting"
# Inserted as [a] audited so Phase 5 Step 1 queue filter picks it up immediately.
new_row = f"| [a] audited | {cross_slug} | (global) | — | — | {cross_dir}/TASKS.md |\n"

# Idempotent: if a row for this cross-slug already exists, update it in place; else insert as first row.
existing_row_re = re.compile(
    rf'^\|[^|]*\|\s*{re.escape(cross_slug)}\s*\|[^\n]*\n',
    re.MULTILINE
)
if existing_row_re.search(content):
    # Update existing row (replace the whole row)
    content = existing_row_re.sub(new_row, content)
    print(f"updated existing {cross_slug} row in MANIFEST.md")
else:
    # Insert immediately after the header row separator line
    content = re.sub(
        r'(\|[-| ]+\|\n)',
        r'\1' + new_row,
        content,
        count=1
    )
    print(f"inserted {cross_slug} as first row in MANIFEST.md")

# Atomic write: write to a tmp file then os.replace to prevent partial-write corruption.
import os as _os
tmp = manifest_path + ".tmp"
with open(tmp, "w") as f:
    f.write(content)
_os.replace(tmp, manifest_path)
PYEOF
```

### Step 7 — Emit telemetry and checkpoint

`G_COUNT`, `C_COUNT`, and `R_COUNT` were computed in Step 5 via Python. Reuse those values directly (do not recompute with grep):

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cross_cutting_classified \
  "$(printf '{"slug":"%s","global_tasks":%d,"per_component_context":%d,"risks":%d}' \
     "$SLUG" "$G_COUNT" "$C_COUNT" "$R_COUNT")"

cp "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase2-cross-cutting.md"
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":2,"name":"cross-cutting","wall_ms":%d,"user_wait_ms":%d}' \
     "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

---

## Phase 3 — Per-component audits

### Overview

Iterate every component in MANIFEST with state `[ ] pending`, **excluding** any row whose slug ends in `-cross-cutting` or whose component column is `(global)` — the synthetic cross-cutting component inserted by Phase 2 (T003) is handled separately in Phase 5 and must not be re-audited here. For each qualifying component, run Steps 1–8 below.

### Step 0 — Phase setup

```bash
T0_PHASE3=$(date +%s%3N)
USER_WAIT_MS_PHASE3=0

# Resolve STYLE.md absolute path once for the whole phase
STYLE_MD_PATH=""
if [ "$NO_STYLE" != "true" ] && [ -f "./STYLE.md" ]; then
  STYLE_MD_PATH="$(pwd)/STYLE.md"
fi

# Split DIMENSIONS csv into an array
IFS=',' read -ra DIM_ARRAY <<< "$DIMENSIONS"
```

### Step 1 — Read MANIFEST and collect pending components

Parse MANIFEST.md to collect rows with state `[ ] pending`. Process them in the order they appear (synthetic `<slug>-cross-cutting` is first if present).

```bash
python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" <<'PYEOF'
import re, sys, json

manifest_path = sys.argv[1]
with open(manifest_path) as f:
    content = f.read()

# Parse table rows: | state | component | slug | ... |
rows = []
for line in content.splitlines():
    line = line.strip()
    if not line.startswith('|') or line.startswith('|---') or line.startswith('| State'):
        continue
    cells = [c.strip() for c in line.split('|')]
    # cells[0] is empty (leading |), cells[1]=state, cells[2]=component, cells[3]=slug, cells[4]=findings, cells[5]=bail, cells[6]=tasks
    if len(cells) < 7:
        continue
    state = cells[1]
    slug  = cells[3]
    comp  = cells[2]
    # Synthetic cross-cutting handled in Phase 2 (T003); skip from Phase 3 iteration
    if slug.endswith('-cross-cutting') or comp == '(global)':
        continue
    if '[ ] pending' in state or state == '[ ] pending':
        rows.append({
            "state":     state,
            "component": comp,
            "slug":      slug,
            "tasks_md":  cells[6],
        })

print(json.dumps(rows))
PYEOF
```

Capture the JSON list into `PENDING_ROWS`. Iterate over it in the loop below.

### Step 2 — Per-component loop

For each entry in `PENDING_ROWS`, execute Steps 2a through 2h.

#### Step 2a — Mark `[~] auditing` and emit start event

Update the MANIFEST row immediately before any dispatch:

```bash
python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" <<'PYEOF'
import re, sys, os

def manifest_write(path, content):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, path)

manifest_path = sys.argv[1]
comp_slug     = sys.argv[2]

with open(manifest_path) as f:
    content = f.read()

# Replace the [ ] pending cell for this slug with [~] auditing
# Match the row by slug in the 4th pipe-cell (state | component | slug | ...)
pattern = re.compile(
    r'(\|\s*)\[ \] pending(\s*\|(?:[^|\n]*\|){1}\s*' + re.escape(comp_slug) + r'\s*\|)',
    re.MULTILINE
)
updated = pattern.sub(r'\1[~] auditing\2', content, count=1)
manifest_write(manifest_path, updated)
PYEOF

bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" component_audit_start \
  "$(printf '{"component":"%s","dimensions":"%s"}' "$COMP_SLUG" "$DIMENSIONS")"
```

#### Step 2b — Create per-component plan dir + minimal SPEC.md and PLAN.md

```bash
COMP_PLAN_DIR="$(dirname "$Z_HARNESS_PLAN_DIR")/${SLUG}-${COMP_SLUG}"
mkdir -p "$COMP_PLAN_DIR"
```

Write `$COMP_PLAN_DIR/SPEC.md`:

```markdown
# Spec — <uplift-slug>-<component-slug>

Audit-derived uplift for `<component path>`; findings in REPORT.md.
```

Write `$COMP_PLAN_DIR/PLAN.md`:

```markdown
# Plan — <uplift-slug>-<component-slug>

Goal: address all CRITICAL and HIGH severity findings surfaced in REPORT.md.
Non-goals: structural refactors beyond the cited findings.

See REPORT.md for full findings and TASKS.md for the actionable queue.
```

#### Step 2c — Extract cross-cutting context for this component

Filter CROSS-CUTTING.md for `per-component-context` rows whose `component:` marker exactly matches `COMP_SLUG`:

```bash
CROSS_CUTTING_CONTEXT="$(python3 - "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" "$COMP_SLUG" <<'PYEOF'
import re, sys

cc_path   = sys.argv[1]
comp_slug = sys.argv[2]

try:
    with open(cc_path) as f:
        content = f.read()
except OSError:
    print("")
    sys.exit(0)

# Extract the Per-component context section
section_match = re.search(
    r'## Per-component context \(inform audits\)\n(.*?)(?=\n## |\Z)',
    content, re.DOTALL
)
if not section_match:
    print("")
    sys.exit(0)

section = section_match.group(1)
matched = []
for line in section.splitlines():
    line = line.strip()
    if not line.startswith('-'):
        continue
    # Exact slug match: look for "component: <comp_slug>" as a whole word/token
    # The format is: - C-NNN — component: <slug> — <description>
    m = re.search(r'component:\s*(\S+)', line)
    if m and m.group(1) == comp_slug:
        matched.append(line)

print('\n'.join(matched))
PYEOF
)"
```

#### Step 2d — Dispatch auditors in parallel (one per dimension)

Build the `rubric_path` for each dimension: pass `$STYLE_MD_PATH` when the dimension is `cleanliness` or `design` AND `STYLE_MD_PATH` is non-empty; pass empty string otherwise.

Dispatch ALL dimension auditors **in a single message** (parallel `Agent(...)` calls). Each auditor writes its findings to `$COMP_PLAN_DIR/findings-<dim>.md` and returns a structured summary.

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this parallel auditor dispatch requirement to the user and skip the Agent() calls. Per-component dimension audits are required for the REPORT.md; drivers that skip them must warn the user that audit findings have been bypassed. -->
```
# Example for DIMENSIONS="correctness,cleanliness,design"
Agent(
  subagent_type="auditor",
  description="correctness audit of <component> for <slug>",
  prompt="DIMENSION: correctness
TARGET: <component path> — component <comp-slug> of uplift run <slug>
RUBRIC_PATH:
$BASE: <abs path to COMP_PLAN_DIR>
cross_cutting_context: <CROSS_CUTTING_CONTEXT>

Follow your agent definition. Emit findings to $BASE/findings-correctness.md and return STATUS + COUNTS + VERDICT."
)
Agent(
  subagent_type="auditor",
  description="cleanliness audit of <component> for <slug>",
  prompt="DIMENSION: cleanliness
TARGET: <component path> — component <comp-slug> of uplift run <slug>
RUBRIC_PATH: <abs path to STYLE.md, or empty string>
$BASE: <abs path to COMP_PLAN_DIR>
cross_cutting_context: <CROSS_CUTTING_CONTEXT>

Follow your agent definition. Emit findings to $BASE/findings-cleanliness.md and return STATUS + COUNTS + VERDICT."
)
Agent(
  subagent_type="auditor",
  description="design audit of <component> for <slug>",
  prompt="DIMENSION: design
TARGET: <component path> — component <comp-slug> of uplift run <slug>
RUBRIC_PATH: <abs path to STYLE.md, or empty string>
$BASE: <abs path to COMP_PLAN_DIR>
cross_cutting_context: <CROSS_CUTTING_CONTEXT>

Follow your agent definition. Emit findings to $BASE/findings-design.md and return STATUS + COUNTS + VERDICT."
)
```

Key dispatch rules:

- `rubric_path` is the **absolute path** to STYLE.md (or empty string). Never inline STYLE.md content.
- `rubric_path` is non-empty **only** when `dim ∈ {cleanliness, design}` AND `STYLE_MD_PATH` is non-empty.
- All auditors for this component are dispatched simultaneously in one message — never serialized.
<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the auditor-failed recovery question (retry / skip dimension / skip component / abort Phase 3) via their native channel. Silent omission is forbidden. -->
- If any auditor returns `unable_to_complete`:

  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
    '{"phase":3,"reason":"auditor_failed"}'
  _WAIT_T0=$(date +%s%3N)
  # AskUserQuestion: retry / skip that dimension / skip the entire component / abort Phase 3
  USER_WAIT_MS_PHASE3=$(( USER_WAIT_MS_PHASE3 + $(date +%s%3N) - _WAIT_T0 ))
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
    "$(printf '{"phase":3,"wall_ms":%d}' "$(( $(date +%s%3N) - _WAIT_T0 ))")"
  ```

  On retry, re-dispatch only the failed dimension.

#### Step 2e — Merge per-dimension findings into REPORT.md

After all auditors for this component return, merge their findings files into `$COMP_PLAN_DIR/REPORT.md`:

```markdown
# Audit — <component path>

- **Date (UTC):** YYYY-MM-DDTHH:MMZ
- **Component:** <component path> (slug: <comp-slug>)
- **Uplift run:** <slug>
- **Dimensions audited:** <comma-separated>
- **Rubric:** <abs path to STYLE.md or "generic">

## Summary
- <2-5 bullets across all dimensions>

## Findings — correctness
<verbatim from findings-correctness.md>

## Findings — cleanliness
<verbatim from findings-cleanliness.md>

## Findings — design
<verbatim from findings-design.md>

... (one section per dimension in DIMENSIONS order)

## Cross-dimension findings
<findings flagged by multiple auditors via CROSS_DIMENSION: lines — consolidate here>

## Verdicts
- correctness: PASS | NEEDS-WORK | BLOCKED
- cleanliness: ...
- design:      KEEP | REFACTOR | SCRAP
```

#### Step 2f — Bundled cross-LLM consult on REPORT.md

Dispatch `consultant-primary` and `consultant-secondary` in a **single message** (parallel):

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this parallel audit-review consultant dispatch requirement to the user and skip the Agent() calls. The cross-LLM review of REPORT.md is required to catch missed and trivial findings; drivers that skip it must warn the user that the audit consult has been bypassed. -->
```
Agent(
  subagent_type="consultant-primary",
  description="Audit findings review (primary) for <comp-slug>",
  prompt="MODE: audit-review

A component has been audited across <dimensions>. Here is the full REPORT:

<paste REPORT.md contents>

Two asks:
1. What significant findings are MISSING — issues the dimension auditors should have caught but didn't?
2. Which listed findings are TRIVIAL or speculative and should be dropped before promotion to TASKS.md?

Be specific. Cite path:line. Severity-rank any additions.

One reason each addition might be wrong: provide a brief counter-argument alongside each addition before accepting it."
)
Agent(
  subagent_type="consultant-secondary",
  description="Audit findings review (secondary) for <comp-slug>",
  prompt="MODE: audit-review

<same prompt body as above>"
)
```

When both return:

1. For each proposed addition: apply the "one reason it might be wrong" check before accepting.
2. For each suggested drop: confirm by re-reading the cited evidence.
3. Append `## Consult additions` and `## Consult drops` sections to REPORT.md noting changes and which consultant flagged them.

Archive transcripts:

```bash
echo "$PRIMARY_TRANSCRIPT"   > "$COMP_PLAN_DIR/archive-consult-primary.md"
echo "$SECONDARY_TRANSCRIPT" > "$COMP_PLAN_DIR/archive-consult-secondary.md"
```

#### Step 2g — Auto-bail check

Count findings in the post-consult REPORT.md:

```bash
CRIT_HIGH_COUNT="$(python3 - "$COMP_PLAN_DIR/REPORT.md" <<'PYEOF'
import re, sys
with open(sys.argv[1]) as f:
    text = f.read()
# Parse findings structurally: split on finding-start markers, then inspect each block's
# header for a CRITICAL or HIGH severity tag. This avoids counting prose mentions.
# Recognises three auditor output formats:
#   1. ### [CRITICAL] <subject>  (auditor.md native format)
#   2. - F-NNN [CRITICAL] ...    (bullet + tag)
#   3. Severity: CRITICAL        (key-value inside block)
finding_start_re = re.compile(
    r'^\s*#{2,4}\s*\[\s*(?:CRITICAL|HIGH|MEDIUM|LOW)\s*\]'
    r'|^\s*[-*]\s+(?:F|C|P|D)-\d+'
    r'|^\s*#{2,4}\s+(?:Finding\s+\d+|F-\d+|C-\d+|P-\d+|D-\d+)',
    re.MULTILINE | re.IGNORECASE
)
positions = [m.start() for m in finding_start_re.finditer(text)]
positions.append(len(text))
crit_high = 0
for i in range(len(positions) - 1):
    block = text[positions[i]:positions[i+1]]
    head = block[:300]
    # Format 1: ### [CRITICAL] or ### [HIGH] header line
    if re.match(r'^\s*#{2,4}\s*\[\s*(CRITICAL|HIGH)\s*\]', head, re.IGNORECASE):
        crit_high += 1
    # Format 2: bullet with inline tag  - F-NNN [CRITICAL]
    elif re.match(r'^\s*[-*]\s+(?:F|C|P|D)-\d+\s*\[\s*(?:CRITICAL|HIGH)\s*\]', head, re.IGNORECASE):
        crit_high += 1
    # Format 3: Severity: CRITICAL|HIGH field inside block
    elif re.search(r'\bSeverity\s*:?\s*(CRITICAL|HIGH)\b', head, re.IGNORECASE):
        crit_high += 1
print(crit_high)
PYEOF
)"

TOTAL_COUNT="$(python3 - "$COMP_PLAN_DIR/REPORT.md" <<'PYEOF'
import re, sys
with open(sys.argv[1]) as f:
    text = f.read()
# Count discrete finding entries by their structural start markers.
# Recognises ### [SEVERITY] headers (auditor.md native), bullet F/C/P/D-NNN markers,
# and legacy ### Finding-NNN headers.
finding_start_re = re.compile(
    r'^\s*#{2,4}\s*\[\s*(?:CRITICAL|HIGH|MEDIUM|LOW)\s*\]'
    r'|^\s*[-*]\s+(?:F|C|P|D)-\d+'
    r'|^\s*#{2,4}\s+(?:Finding\s+\d+|F-\d+|C-\d+|P-\d+|D-\d+)',
    re.MULTILINE | re.IGNORECASE
)
print(len(finding_start_re.findall(text)))
PYEOF
)"
```

**Bail condition:** `TOTAL_COUNT > 30` OR `CRIT_HIGH_COUNT > 10`.

If bail is triggered:

1. Prepend the bail header to REPORT.md:

   ```markdown
   # BAILED — exceeds /z-audit thresholds

   Component: <component path>
   Total findings: <N>
   CRITICAL+HIGH findings: <N>
   Bail reason: crit_high_volume

   ---

   <existing REPORT.md content below>
   ```

2. Compute `OTHER_COMP_PATHS` from MANIFEST (all Path-column values except the bailing component and the synthetic cross-cutting row), then run a text-grep to find references:

   ```bash
   COMP_BASENAME="$(basename "$COMP_PATH")"
   # Derive OTHER_COMP_PATHS from MANIFEST: all Path-column values except COMP_PATH and cross-cutting synthetic rows
   OTHER_COMP_PATHS="$(python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_PATH" <<'INNEREOF'
import sys
manifest_path = sys.argv[1]
current_path  = sys.argv[2]
with open(manifest_path) as f:
    content = f.read()
paths = []
for line in content.splitlines():
    line = line.strip()
    if not line.startswith('|') or line.startswith('|---') or line.startswith('| State'):
        continue
    cells = [c.strip() for c in line.split('|')]
    # cells: ['', state, component(path), slug, findings, bail, tasks, '']
    if len(cells) < 7:
        continue
    comp_path = cells[2]
    slug      = cells[3]
    # Skip current bailing component and synthetic cross-cutting row
    if comp_path == current_path or slug.endswith('-cross-cutting') or comp_path == '(global)':
        continue
    if comp_path and comp_path != '—' and comp_path != '-':
        paths.append(comp_path)
print(' '.join(paths))
INNEREOF
   )"
   if [ -n "$OTHER_COMP_PATHS" ]; then
     DEPS_FOUND="$(git grep -l "$COMP_BASENAME" -- $OTHER_COMP_PATHS 2>/dev/null || true)"
   else
     DEPS_FOUND=""
   fi
   ```

3. Append the dependents section to REPORT.md:

   ```markdown
   ## Potential dependents (text-grep — incomplete; validate manually for critical APIs)

   The following files in other components contain a text reference to `<component-basename>`.
   This is a heuristic grep — not a precise dependency graph. Manual validation is required
   before concluding any API contract exists.

   <list of DEPS_FOUND files, one per line; or "(none found)" if empty>
   ```

4. Append the dependents warning block to MANIFEST.md's `## Dependents warnings (post-bail)` section (create the section if absent):

   ```bash
   python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "$COMP_PATH" "$DEPS_FOUND" <<'PYEOF'
   import sys, re, os

   def manifest_write(path, content):
       tmp = path + ".tmp"
       with open(tmp, "w") as f:
           f.write(content)
       os.replace(tmp, path)

   manifest_path = sys.argv[1]
   comp_slug     = sys.argv[2]
   comp_path     = sys.argv[3]
   deps_raw      = sys.argv[4]

   with open(manifest_path) as f:
       content = f.read()

   deps_list = [d.strip() for d in deps_raw.splitlines() if d.strip()] if deps_raw.strip() else []
   deps_str  = '\n'.join(f'  - {d}' for d in deps_list) if deps_list else '  - (none found)'

   warn_entry = (
       f"- {comp_slug} bailed (crit_high_volume); text-grep references found in "
       f"(Potential / incomplete — validate manually for critical APIs):\n{deps_str}\n"
   )

   section_header = "## Dependents warnings (post-bail)"
   if section_header in content:
       content = content.replace(section_header, section_header + '\n' + warn_entry, 1)
   else:
       content = content.rstrip() + f"\n\n{section_header}\n{warn_entry}"

   manifest_write(manifest_path, content)
   PYEOF
   ```

5. Mark MANIFEST row as `[!] bailed: crit_high_volume` and populate Audit findings + Bail reason columns:

   ```bash
   python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "crit_high_volume" \
     "$TOTAL_COUNT" "$CRIT_HIGH_COUNT" <<'PYEOF'
   import re, sys, os

   def manifest_write(path, content):
       tmp = path + ".tmp"
       with open(tmp, "w") as f:
           f.write(content)
       os.replace(tmp, path)

   manifest_path = sys.argv[1]
   comp_slug     = sys.argv[2]
   bail_reason   = sys.argv[3]
   total_count   = int(sys.argv[4])
   crit_high     = int(sys.argv[5])

   with open(manifest_path) as f:
       content = f.read()

   findings_str = f"{total_count} ({crit_high} HIGH)"

   # Update the row matching comp_slug: replace state AND populate Audit findings + Bail reason columns.
   # Row format: | state | component | slug | findings | bail | tasks |
   def replace_row(m):
       # m.group(0) is the full row; rebuild with updated cells
       row = m.group(0)
       cells = row.split('|')
       # cells: ['', state, component, slug, findings, bail, tasks, '']
       if len(cells) < 8:
           return row
       cells[1] = f" [!] bailed: {bail_reason} "
       cells[4] = f" {findings_str} "
       cells[5] = f" {bail_reason} "
       # TASKS.md stays as-is (partial REPORT.md only — leave existing value)
       return '|'.join(cells)

   pattern = re.compile(
       r'\|[^|\n]*\|\s*[^|\n]*\|\s*' + re.escape(comp_slug) + r'\s*\|[^\n]*\|',
       re.MULTILINE
   )
   updated = pattern.sub(replace_row, content, count=1)
   manifest_write(manifest_path, updated)
   PYEOF
   ```

6. Emit `component_audit_done` with `bailed: true`:

   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" component_audit_done \
     "$(printf '{"component":"%s","findings_total":%d,"findings_crit_high":%d,"bailed":true,"bail_reason":"crit_high_volume"}' \
        "$COMP_SLUG" "$TOTAL_COUNT" "$CRIT_HIGH_COUNT")"
   ```

7. **Continue to next component** — do not generate TASKS.md or run the reviewer.

#### Step 2h — Promote findings to TASKS.md (non-bail path)

Only reached when bail condition is NOT met.

Write `$COMP_PLAN_DIR/TASKS.md` in the exact format `/z-implement-all` consumes (mirror `/z-audit` Phase 5 shape):

```markdown
# Audit TASKS — <component path>

Status legend: `[ ]` pending · `[~]` in_progress · `[x]` done.

### [ ] T001 — [SEVERITY] short subject
- One-paragraph context: why this matters, what evidence supports it (cite REPORT.md finding ID).
- **Files:** `<path>:<line>` (modified).
- **Depends on:** none | T00X.
- **Acceptance:** verifiable criteria.
- **Complexity:** low | medium | high

### [ ] T002 — [SEVERITY] ...
```

Severity prefix: `[CRITICAL] | [HIGH] | [MED] | [LOW]`. Group by phase (Phase A / B / ...) when tasks have ordering dependencies. Only actionable findings (those with a clear fix) go into TASKS.md; observations without a concrete recommendation stay in REPORT.md only.

#### Step 2i — Dispatch reviewer over TASKS.md (mandatory safety gate)

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this reviewer dispatch requirement to the user and skip the Agent() call. The reviewer is the mandatory safety gate over audit-produced TASKS.md; drivers that skip it must warn the user that TASKS.md soundness has not been verified. -->
```
Agent(
  subagent_type="reviewer",
  description="Review of audit TASKS for <comp-slug>",
  prompt="task id: <slug>-<comp-slug>-audit-tasks
task description: review the audit-produced TASKS.md for soundness — would executing these tasks make the target better or risk regression?
acceptance criteria: every task addresses a real finding in REPORT.md with a verifiable acceptance line
diff.patch path: (n/a — review the file directly)
changed files: <abs path to COMP_PLAN_DIR/TASKS.md>
relevant_docs:
$BASE: <abs path to COMP_PLAN_DIR>

Flag: tasks that would regress invariants, tasks with vague acceptance, severity inflation, scope creep beyond the cited finding."
)
```

Parse the return:

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the reviewer second-failure decision (continue / skip component / abort Phase 3) via their native channel. Silent omission is forbidden. -->
- **Blockers** → re-edit the affected TASKS.md entries in-place; re-run the reviewer once. If the second review still has Blockers:

  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
    '{"phase":3,"reason":"reviewer_blocker"}'
  _WAIT_T0=$(date +%s%3N)
  # AskUserQuestion: describe the issue; offer to continue / skip component / abort Phase 3
  USER_WAIT_MS_PHASE3=$(( USER_WAIT_MS_PHASE3 + $(date +%s%3N) - _WAIT_T0 ))
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
    "$(printf '{"phase":3,"wall_ms":%d}' "$(( $(date +%s%3N) - _WAIT_T0 ))")"
  ```
- **Majors** → fix in-place, then accept.
- **No Blockers/Majors** → accept and continue.

Update the MANIFEST row's TASKS.md column to `<abs path to COMP_PLAN_DIR/TASKS.md>`.

#### Step 2j — Mark `[a] audited` and emit done event

```bash
python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "$COMP_PLAN_DIR/TASKS.md" \
  "$TOTAL_COUNT" "$CRIT_HIGH_COUNT" <<'PYEOF'
import re, sys, os

def manifest_write(path, content):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, path)

manifest_path = sys.argv[1]
comp_slug     = sys.argv[2]
tasks_path    = sys.argv[3]
total_count   = int(sys.argv[4])
crit_high     = int(sys.argv[5])

with open(manifest_path) as f:
    content = f.read()

findings_str = f"{total_count} ({crit_high} HIGH)"

# Update the row matching comp_slug (column 3): set state, findings, and TASKS.md columns.
# Row format: | state | component | slug | findings | bail | tasks |
# Filter by slug column to avoid modifying the wrong row (B2 fix).
def replace_row(m):
    row = m.group(0)
    cells = row.split('|')
    # cells: ['', state, component, slug, findings, bail, tasks, '']
    if len(cells) < 8:
        return row
    if cells[3].strip() != comp_slug:
        return row  # slug mismatch — do not mutate this row
    cells[1] = " [a] audited "
    cells[4] = f" {findings_str} "
    cells[6] = f" {tasks_path} "
    return '|'.join(cells)

# Match any row that contains the slug in column position 3 with auditing state
pattern = re.compile(
    r'\|[^|\n]*\|\s*[^|\n]*\|\s*' + re.escape(comp_slug) + r'\s*\|[^\n]*\|',
    re.MULTILINE
)
updated = pattern.sub(replace_row, content)
manifest_write(manifest_path, updated)
PYEOF

bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" component_audit_done \
  "$(printf '{"component":"%s","findings_total":%d,"findings_crit_high":%d,"bailed":false,"bail_reason":""}' \
     "$COMP_SLUG" "$TOTAL_COUNT" "$CRIT_HIGH_COUNT")"
```

### Step 3 — Checkpoint and phase telemetry

After all components have been processed:

```bash
cp "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-audits.md"
WALL_MS_PHASE3=$(( $(date +%s%3N) - T0_PHASE3 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":3,"name":"per-component-audits","wall_ms":%d,"user_wait_ms":%d}' \
     "$WALL_MS_PHASE3" "$USER_WAIT_MS_PHASE3")"
```

---

## Phase 4 — Review gate

Record `T0=$(date +%s%3N)` at phase start.

### Step 1 — Aggregate queue summary from MANIFEST

Parse MANIFEST.md to compute counts:

```bash
PHASE4_SUMMARY="$(python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$SLUG" <<'PYEOF'
import re, sys, json, os

manifest_path = sys.argv[1]
slug          = sys.argv[2]

with open(manifest_path) as f:
    content = f.read()

audited      = []
bailed       = []
dep_warnings = []
total_tasks  = 0

for line in content.splitlines():
    line = line.strip()
    if not line.startswith('|') or line.startswith('|---') or line.startswith('| State'):
        continue
    cells = [c.strip() for c in line.split('|')]
    # cells[0] empty, [1]=state, [2]=component, [3]=slug, [4]=findings, [5]=bail, [6]=tasks
    if len(cells) < 7:
        continue
    state    = cells[1]
    comp     = cells[2]
    findings = cells[4]
    tasks_md = cells[6] if len(cells) > 6 else ''

    if '[a] audited' in state:
        audited.append(comp)
        # Count tasks in TASKS.md if path is valid
        if tasks_md and tasks_md not in ('—', '-', ''):
            tasks_path = tasks_md.strip()
            try:
                with open(tasks_path) as tf:
                    task_text = tf.read()
                pending = len(re.findall(r'^\s*###\s*\[\s*\]', task_text, re.MULTILINE))
                total_tasks += pending
            except OSError:
                pass
    elif '[!] bailed' in state:
        bail_reason = cells[5] if len(cells) > 5 else 'unknown'
        bailed.append(f"{comp} ({bail_reason.strip()})")

# Count dep-warnings section entries
dep_section = re.search(r'## Dependents warnings \(post-bail\)(.*?)(?=\n## |\Z)', content, re.DOTALL)
if dep_section:
    dep_warnings = [l.strip() for l in dep_section.group(1).splitlines()
                    if l.strip().startswith('-')]

result = {
    "audited_count":  len(audited),
    "total_tasks":    total_tasks,
    "bailed_list":    bailed,
    "dep_warn_count": len(dep_warnings),
    "audited_list":   audited,
}
print(json.dumps(result))
PYEOF
)"

AUDITED_COUNT="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d['audited_count'])" "$PHASE4_SUMMARY")"
TOTAL_TASKS="$(python3 -c  "import json,sys; d=json.loads(sys.argv[1]); print(d['total_tasks'])"   "$PHASE4_SUMMARY")"
BAILED_LIST="$(python3 -c  "import json,sys; d=json.loads(sys.argv[1]); print('\n'.join(d['bailed_list']))" "$PHASE4_SUMMARY")"
BAILED_COUNT="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(len(d['bailed_list']))" "$PHASE4_SUMMARY")"
DEP_WARN_COUNT="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d['dep_warn_count'])" "$PHASE4_SUMMARY")"
```

### Step 2 — Write checkpoint and push-notify

Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/phase4-review-gate.md`:

```bash
python3 - "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase4-review-gate.md" \
  "$SLUG" "$PHASE4_SUMMARY" <<'PYEOF'
import json, sys, os
from datetime import datetime, timezone

out_path = sys.argv[1]
slug     = sys.argv[2]
d        = json.loads(sys.argv[3])

lines = [
    f"# Phase 4 — Review gate checkpoint — {slug}",
    f"",
    f"Generated: {datetime.now(timezone.utc).isoformat()}",
    f"",
    f"## Queue summary",
    f"- Components audited: {d['audited_count']}",
    f"- Total tasks queued: {d['total_tasks']}",
    f"- Bailed components:  {len(d['bailed_list'])}",
    f"- Dep warnings:       {d['dep_warn_count']}",
    f"",
]
if d['bailed_list']:
    lines.append("## Bailed components")
    for b in d['bailed_list']:
        lines.append(f"- {b}")
    lines.append("")

os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, "w") as f:
    f.write("\n".join(lines) + "\n")
print("wrote phase4-review-gate.md")
PYEOF
```

Push-notify the user with the queue summary.

Present the following summary (no AskUser — this is informational only):

> **Uplift queue ready — `<slug>`**
>
> - Components audited: `<AUDITED_COUNT>`
> - Total tasks queued: `<TOTAL_TASKS>` (across all audited components)
> - Bailed components: `<BAILED_COUNT>` `<if > 0: list each on its own line>`
> - Dependents warnings: `<DEP_WARN_COUNT>` `<if > 0: note "see MANIFEST.md Dependents warnings section">`
>
> Phase 5 will prompt you per-component before dispatching any implementation.

```bash
if grep -qE '^\| .* \| .*-cross-cutting \|' "$Z_HARNESS_PLAN_DIR/MANIFEST.md"; then
  echo "Note: '${SLUG}-cross-cutting' will be implemented first (per SPEC §Phase 5)."
fi
```

### Step 3 — Phase telemetry

```bash
cp "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase4-manifest.md"
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":4,"name":"review-gate","wall_ms":%d,"user_wait_ms":0,"audited":%d,"total_tasks":%d,"bailed":%d}' \
     "$WALL_MS" "$AUDITED_COUNT" "$TOTAL_TASKS" "$BAILED_COUNT")"
```

---

## Phase 5 — Sequential implement

**Two-step handoff model (read this first):**
Phase 5 cannot autonomously invoke `/z-implement-all` — slash commands cannot invoke other slash commands. Instead, Phase 5 operates as follows:
- **Step 2c (first invocation):** After the user confirms a component, Phase 5 prints the explicit `/z-implement-all` command for the user to run, marks MANIFEST `[i] implementing`, and EXITS cleanly with a RESUME INSTRUCTION. The user then runs `/z-implement-all` independently.
- **Resume path (next invocation):** When `/z-uplift` is re-invoked, it detects the `[i] implementing` row in Step 2a. It re-reads the per-component TASKS.md and if all rows are `[x]` (zero `[ ]` remaining), automatically transitions MANIFEST to `[x] done` and emits `component_implement_done`. If pending rows remain, it presents an AskUserQuestion (resume / mark done / skip / abort). The "Mark done" option in Step 2a ALWAYS verifies zero `[ ]` rows before accepting the transition.

Record `T0=$(date +%s%3N)` at phase start.

### Step 1 — Build the ordered implementation queue

Parse MANIFEST.md to collect rows with state `[a] audited` **plus** any `[i] implementing` rows (interrupted on a prior invocation). Apply the ordering rule: the synthetic `<slug>-cross-cutting` row is always processed first, regardless of its physical position in the table.

```bash
IMPL_QUEUE="$(python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$SLUG" <<'PYEOF'
import re, sys, json

manifest_path = sys.argv[1]
slug          = sys.argv[2]

with open(manifest_path) as f:
    content = f.read()

cross_cutting_row = None
other_rows        = []

for line in content.splitlines():
    line = line.strip()
    if not line.startswith('|') or line.startswith('|---') or line.startswith('| State'):
        continue
    cells = [c.strip() for c in line.split('|')]
    # cells[0]=empty, [1]=state, [2]=component, [3]=slug, [4]=findings, [5]=bail, [6]=tasks
    if len(cells) < 7:
        continue
    state    = cells[1]
    comp     = cells[2]
    row_slug = cells[3]
    tasks_md = cells[6] if len(cells) > 6 else ''

    actionable = '[a] audited' in state or '[i] implementing' in state
    if not actionable:
        continue

    row = {
        "state":     state,
        "component": comp,
        "slug":      row_slug,
        "tasks_md":  tasks_md,
        "implementing": '[i] implementing' in state,
    }

    # Synthetic cross-cutting goes first.
    # MANIFEST row written by Phase 2: Component="{slug}-cross-cutting", Slug="(global)".
    # Accept either form to handle both the canonical write and any manual edits.
    if comp.endswith('-cross-cutting') or row_slug == '(global)':
        cross_cutting_row = row
    else:
        other_rows.append(row)

ordered = ([cross_cutting_row] if cross_cutting_row else []) + other_rows
print(json.dumps(ordered))
PYEOF
)"
```

### Step 2 — Per-component implement loop

Iterate over each row in `IMPL_QUEUE`. For each component, execute Steps 2a through 2e.

#### Step 2a — Handle `[i] implementing` (interrupted resume)

If the row state is `[i] implementing` (set on a prior invocation that was interrupted before completion):

First, verify the per-component TASKS.md to check whether `/z-implement-all` already completed:

```bash
RESUME_PENDING_COUNT="$(python3 - "$COMP_TASKS_MD" <<'PYEOF'
import re, sys
try:
    with open(sys.argv[1]) as f:
        text = f.read()
    print(len(re.findall(r'^\s*###\s*\[\s*\]', text, re.MULTILINE)))
except OSError:
    print(0)
PYEOF
)"
```

If `RESUME_PENDING_COUNT == 0` (all tasks are `[x]`): automatically transition without AskUserQuestion — run the manifest_replace_row block from Step 2d with state `[x] done`, emit `component_implement_done`, and continue to the next component. Skip the AskUserQuestion below.

```bash
# Run manifest_replace_row (Step 2d block) with new_state="[x] done", then:
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" component_implement_done \
  "$(printf '{"component":"%s","completed":true,"halted":false}' "$COMP_SLUG")"
```

If `RESUME_PENDING_COUNT > 0`:

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the interrupted-resume question (resume / mark as done / skip / abort) via their native channel. Silent omission is forbidden. -->
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
  "$(printf '{"phase":5,"reason":"interrupted_resume","component":"%s"}' "$COMP_SLUG")"
_WAIT_T0=$(date +%s%3N)
```

Present `AskUserQuestion`:

> Component `<component>` is in state `[i] implementing` — it was being implemented when the last invocation was interrupted. `<RESUME_PENDING_COUNT>` pending task(s) remain in `<COMP_TASKS_MD>`.
>
> How would you like to proceed?
> 1. Resume — run `/z-implement-all --tasks=<tasks_md>` now to continue implementation
> 2. Mark as done — the implementation was completed manually; update MANIFEST to `[x] done`
> 3. Skip — mark as `[s] skipped: user` and move on
> 4. Abort — leave all remaining components unchanged and exit

After the user responds:

```bash
USER_WAIT_MS_THIS_PHASE=$(( USER_WAIT_MS_THIS_PHASE + $(date +%s%3N) - _WAIT_T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
  "$(printf '{"phase":5,"wall_ms":%d}' "$(( $(date +%s%3N) - _WAIT_T0 ))")"
```

Handle the response:

- **Option 1 (Resume):** continue into Step 2b (treat as a normal proceed).
- **Option 2 (Mark done):** Before accepting the transition, verify the per-component TASKS.md has zero `[ ]` rows:

  ```bash
  PENDING_COUNT="$(python3 - "$COMP_TASKS_MD" <<'PYEOF'
  import re, sys
  try:
      with open(sys.argv[1]) as f:
          text = f.read()
      print(len(re.findall(r'^\s*###\s*\[\s*\]', text, re.MULTILINE)))
  except OSError:
      print(0)
  PYEOF
  )"
  ```

  If `PENDING_COUNT > 0`: refuse the transition — print:
  > Cannot mark done — `<PENDING_COUNT>` pending task(s) remain in `<COMP_TASKS_MD>`. Re-run `/z-implement-all --tasks=<COMP_TASKS_MD>` to finish them first.

  Then re-present the AskUserQuestion for this component (loop back to Step 2a).

  If `PENDING_COUNT == 0`: run the manifest_replace_row block from Step 2d with state `[x] done`, emit `component_implement_done` with `{"completed":true,"halted":false}`, continue to the next component.

- **Option 3 (Skip):** run the manifest_replace_row block from Step 2d with state `[s] skipped: user`, continue to the next component.
- **Option 4 (Abort):** go to Step 2e (abort path).

#### Step 2b — AskUser gate (normal `[a] audited` components)

If the row state was `[a] audited` (not a resume from `[i] implementing`):

Count pending tasks in the TASKS.md to show the user:

```bash
COMP_PENDING_TASKS="$(python3 - "$COMP_TASKS_MD" <<'PYEOF'
import re, sys
try:
    with open(sys.argv[1]) as f:
        text = f.read()
    print(len(re.findall(r'^\s*###\s*\[\s*\]', text, re.MULTILINE)))
except OSError:
    print(0)
PYEOF
)"
```

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the per-component implement gate question (proceed / skip / abort) via their native channel. Silent omission is forbidden. -->
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
  "$(printf '{"phase":5,"reason":"implement_gate","component":"%s"}' "$COMP_SLUG")"
_WAIT_T0=$(date +%s%3N)
```

Present `AskUserQuestion`:

> Implement `<component>` (`<COMP_PENDING_TASKS>` pending tasks)?
>
> Tasks file: `<COMP_TASKS_MD>`
>
> Options:
> 1. Proceed — dispatch `/z-implement-all --tasks=<COMP_TASKS_MD>`
> 2. Skip this component — mark as skipped and move on
> 3. Abort uplift — leave remaining components unchanged and exit

After the user responds:

```bash
USER_WAIT_MS_THIS_PHASE=$(( USER_WAIT_MS_THIS_PHASE + $(date +%s%3N) - _WAIT_T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
  "$(printf '{"phase":5,"wall_ms":%d}' "$(( $(date +%s%3N) - _WAIT_T0 ))")"
```

Handle the response:

- **Proceed:** continue into Step 2c.
- **Skip:** run the manifest_replace_row block in Step 2d with state `[s] skipped: user`; continue to next component.
- **Abort:** go to Step 2e (abort path).

#### Step 2c — Dispatch implementation

Emit `component_implement_start` event and mark MANIFEST `[i] implementing` BEFORE dispatch (so an interrupt is detectable on next resume):

```bash
COMP_TASK_COUNT="$(python3 - "$COMP_TASKS_MD" <<'PYEOF'
import re, sys
try:
    with open(sys.argv[1]) as f:
        text = f.read()
    print(len(re.findall(r'^\s*###\s*\[\s*\]', text, re.MULTILINE)))
except OSError:
    print(0)
PYEOF
)"
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" component_implement_start \
  "$(printf '{"component":"%s","task_count":%d}' "$COMP_SLUG" "$COMP_TASK_COUNT")"

python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "[i] implementing" <<'PYEOF'
import re, sys, os

def manifest_replace_row(path, comp_slug, new_state):
    """Read MANIFEST, replace exactly one row matching comp_slug, write atomically."""
    with open(path) as f:
        content = f.read()

    replacement_count = 0

    def replace_row(m):
        nonlocal replacement_count
        row   = m.group(0)
        cells = row.split('|')
        if len(cells) < 8:
            return row
        if cells[3].strip() != comp_slug:
            return row
        replacement_count += 1
        cells[1] = f" {new_state} "
        return '|'.join(cells)

    pattern = re.compile(
        r'\|[^|\n]*\|\s*[^|\n]*\|\s*' + re.escape(comp_slug) + r'\s*\|[^\n]*\|',
        re.MULTILINE
    )
    updated = pattern.sub(replace_row, content)

    if replacement_count != 1:
        raise ValueError(
            f"manifest_replace_row: expected exactly 1 row matching slug '{comp_slug}', "
            f"got {replacement_count}. MANIFEST not written."
        )

    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(updated)
    os.replace(tmp, path)

manifest_path = sys.argv[1]
comp_slug     = sys.argv[2]
new_state     = sys.argv[3]

manifest_replace_row(manifest_path, comp_slug, new_state)
print(f"marked {comp_slug} as {new_state}")
PYEOF
```

Present the `/z-implement-all` invocation command to the user and instruct them to run it:

> **RESUME INSTRUCTION — run this command now:**
>
> ```
> /z-implement-all --tasks=<COMP_TASKS_MD>
> ```
>
> After `/z-implement-all` completes, re-invoke `/z-uplift` to advance the queue. The next `/z-uplift` invocation will detect the `[i] implementing` row for `<component>`, verify the per-component TASKS.md is fully done (all `[x]`), and transition MANIFEST to `[x] done` automatically.

Then **exit** the current `/z-uplift` invocation cleanly (do not attempt to wait for `/z-implement-all` inline — it is a separate slash command that runs independently). Log `run_end` with `status: pending_implement` before exiting:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_end \
  "$(printf '{"slug":"%s","status":"pending_implement","component":"%s","tasks_md":"%s"}' \
     "$SLUG" "$COMP_SLUG" "$COMP_TASKS_MD")"
```

#### Step 2d — MANIFEST state update helper

This Python block is the canonical `manifest_replace_row` helper for Phase 5 state transitions. It requires exactly one row to match `comp_slug` and raises an error if zero or multiple rows match (preventing silent MANIFEST corruption). Invoke it with the target `new_state` string:

```bash
python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "<new_state>" <<'PYEOF'
import re, sys, os

def manifest_replace_row(path, comp_slug, new_state):
    """Read MANIFEST, replace exactly one row matching comp_slug, write atomically."""
    with open(path) as f:
        content = f.read()

    replacement_count = 0

    def replace_row(m):
        nonlocal replacement_count
        row   = m.group(0)
        cells = row.split('|')
        if len(cells) < 8:
            return row
        if cells[3].strip() != comp_slug:
            return row
        replacement_count += 1
        cells[1] = f" {new_state} "
        return '|'.join(cells)

    pattern = re.compile(
        r'\|[^|\n]*\|\s*[^|\n]*\|\s*' + re.escape(comp_slug) + r'\s*\|[^\n]*\|',
        re.MULTILINE
    )
    updated = pattern.sub(replace_row, content)

    if replacement_count != 1:
        raise ValueError(
            f"manifest_replace_row: expected exactly 1 row matching slug '{comp_slug}', "
            f"got {replacement_count}. MANIFEST not written."
        )

    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(updated)
    os.replace(tmp, path)

manifest_path = sys.argv[1]
comp_slug     = sys.argv[2]
new_state     = sys.argv[3]

manifest_replace_row(manifest_path, comp_slug, new_state)
print(f"marked {comp_slug} as {new_state}")
PYEOF
```

Valid `new_state` values used in Phase 5: `[i] implementing`, `[x] done`, `[s] skipped: user`.

#### Step 2e — Abort path

When the user chooses "Abort" in any AskUser gate above:

1. Do NOT modify the current component's MANIFEST row (leave it in `[a] audited` or `[i] implementing`).
2. Do NOT modify any subsequent component's MANIFEST row.
3. Log `run_end` with `status: aborted_by_user`:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_end \
  "$(printf '{"slug":"%s","status":"aborted_by_user","aborted_at_component":"%s"}' \
     "$SLUG" "$COMP_SLUG")"
```

4. Exit cleanly. Output the message:

> Uplift aborted. Re-invoke `/z-uplift` to resume from `<component>`.

### Step 3 — Emit `component_implement_done` on successful manual-done marking

When the user selects "Mark as done" (Step 2a option 2), emit:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" component_implement_done \
  "$(printf '{"component":"%s","completed":true,"halted":false}' "$COMP_SLUG")"
```

### Step 4 — Phase checkpoint and telemetry

After all components in the queue have been handled (or after the user exits cleanly):

```bash
cp "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase5-implement.md"
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":5,"name":"sequential-implement","wall_ms":%d,"user_wait_ms":%d}' \
     "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

---

## Phase 6 — Finalize

Record `T0=$(date +%s%3N)` at phase start.

Phase 6 closes the uplift run by recording final telemetry, notifying the user with a summary of outcomes (done / skipped / bailed), and flagging any follow-on work. It logs `run_end` with a structured status blob so post-run analysis can compute per-run metrics. If any task in any generated TASKS.md carried a `**DOCS:**` line, Phase 6 surfaces a recommendation to run `/z-maintain-docs` — this keeps the two-tier documentation current after uplift-driven code changes. No code is modified in this phase.

1. Log `run_end` with a status blob:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_end \
  "$(printf '{"slug":"%s","status":"complete","components_done":%d,"components_skipped":%d,"components_bailed":%d}' \
     "$SLUG" "$DONE_COUNT" "$SKIPPED_COUNT" "$BAILED_COUNT")"
```

2. Push-notify the user with the final summary (done / skipped / bailed counts).

3. If any task in any generated TASKS.md carried a `**DOCS:**` line, recommend:

   > "Some tasks carried DOCS tags. Run `/z-maintain-docs` to refresh the two-tier documentation."

Checkpoint and phase telemetry:

```bash
cp "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase6-finalize.md"
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":6,"name":"finalize","wall_ms":%d,"user_wait_ms":0}' "$WALL_MS")"
```

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Setup Step 5 docs-staleness route; Phase 2 Step 4 cross-cutting consultants (primary + secondary); Phase 3 Step 2d dimension auditors (parallel per-component); Phase 3 Step 2f audit-review consultants (primary + secondary); Phase 3 Step 2i reviewer over TASKS.md |
| `ask_user` | yes | Setup Step 1 slug collision confirmation; Setup Step 1 non-obvious slug confirmation; Setup Step 5 docs-staleness route decision; STYLE.md gate missing-style decision; Phase 0 premise concern; Phase 1 Step 2 slug collision disambiguation; Phase 1 Step 5 decomposition confirm; Phase 3 Step 2d auditor-failed recovery; Phase 3 Step 2i reviewer second-failure decision; Phase 5 Step 2a interrupted-resume decision; Phase 5 Step 2b per-component implement gate |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
