---
description: Tiered bulk codebase quality uplift — decompose repo into components, run a repo-wide cross-cutting pass, dispatch per-component audits, produce per-component TASKS.md files, and drive sequential implementation via /z-implement-all.
argument-hint: [--components=<file>] [--component <path>] [--retry-bailed] [--refresh-component <name>] [--dimensions=<csv>] [--cross-cutting=skip] [--no-style]
model: opus
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

---

## Setup

### Step 1 — Derive uplift slug

Derive a slug from the repository name or the first 2–4 words of the user's description: short kebab-case (e.g. "uplift my-app" → `my-app-uplift`; default `<repo-basename>-uplift`).

If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.

Check for an existing slug dir in the canonical plans directory (`z-harness/plans/`). If a MANIFEST.md is found there, this is a **resume** — skip decomposition phases and jump to the next non-terminal MANIFEST state. If only a slug collision without MANIFEST, prompt the user to confirm or choose a different slug.

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

Read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.

### Step 5 — Doc-staleness route check

If `docs/llm/INDEX.json` exists in the repo root, compute staleness across all entries before Phase 0 starts. Read only the lightweight metadata fields (`slug`, `last_updated`, `source_file`). For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`.

Compute `stale_pct = stale_concepts / total_concepts`. Threshold: `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — 20 percent).

If `stale_pct >= threshold`:
- Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md` (artifact for audit trail). Set `ARTIFACT_PATH="$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md"`.
- Push-notify and present `AskUserQuestion`: switch to `/z-maintain-docs` / continue here with stale docs / abandon.
- Do NOT auto-invoke `/z-maintain-docs`.
- After the user responds, emit `plan_route_decision` with the resolved `user_choice` populated:

  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_route_decision \
    "$(printf '{"from_command":"/z-uplift","to_command":"/z-maintain-docs","route_class":"contextual","reason_codes":["docs_stale"],"signals":{"docs_stale_or_drifted":true},"confidence":"high","classifier_used":false,"artifact_path":"%s","route_chain":["/z-uplift","/z-maintain-docs"],"user_choice":"%s"}' \
       "$ARTIFACT_PATH" "$USER_ROUTE_CHOICE")"
  ```

  Where `USER_ROUTE_CHOICE` is one of `"switch"`, `"continue"`, or `"abandon"` based on the user's response.

- If user chose `"continue"`: emit `doc_drift_acknowledged` event and proceed.
- If user chose `"switch"`: halt with the message "Run `/z-maintain-docs` to refresh docs, then re-invoke `/z-uplift`." Do NOT auto-invoke.
- If user chose `"abandon"`: emit `run_end status: aborted_by_user` and exit.

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

If STYLE.md is missing and `NO_STYLE` is not set, push-notify and present `AskUserQuestion`:

> No `STYLE.md` found at the repo root. How would you like to proceed?
> 1. Run `/z-style-init` first (recommended) — after it completes, re-invoke `/z-uplift`
> 2. Continue without STYLE.md (cleanliness+design audits degrade to generic rubric) — equivalent to passing `--no-style`
> 3. Abort

Handle the response (emit the outcome-specific event AFTER the user responds, inside each branch):

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

**Do not take the prompt's premises for granted.** Before proceeding with decomposition, verify:

- Does the codebase actually need bulk uplift, or is there a more targeted `/z-audit` call that's more appropriate?
- Are there any obvious blockers (e.g. the repo is a single-file script with no meaningful component boundaries) that would make `/z-uplift` inappropriate?
- Is there a `MANIFEST.md` already present under `$Z_HARNESS_PLAN_DIR/`? If so, this is a resume — describe the current MANIFEST state to the user and confirm whether they want to resume or restart.

If any concern surfaces, stop and raise it with the user via `AskUserQuestion` before continuing.

If nothing concerning surfaces, write a one-paragraph "premise accepted" summary describing what uplift will cover (component detection strategy, dimensions, STYLE.md status).

Checkpoint: `phase0-premise.md`.

---

## Phase 1 — Decomposition

Record `T0=$(date +%s%3N)` at phase start.

### Step 1 — Resolve components list

If `COMPONENTS_FILE` is set (from `--components=<file>`), read it directly (newline-delimited paths, skip blank lines and lines starting with `#`) and skip auto-detection. Each path in the file is treated as an explicitly-provided component; detection method = `manual`. Jump to Step 3 after loading.

Otherwise run auto-detection via inline Python:

```python
#!/usr/bin/env python3
import os, sys, json, re

repo_root = sys.argv[1]
extra_components = json.loads(sys.argv[2])  # list of {path, method} from --component flags

DENYLIST = {
    "docs", "target", "node_modules", "dist", "build",
    ".git", "z-harness", "__pycache__", ".venv",
}

def to_slug(name):
    """Kebab-case slug: basename lowercased, non-alnum runs replaced with '-', strip leading/trailing '-'."""
    s = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return s or name.lower()

def relpath(p):
    return os.path.relpath(p, repo_root)

components = []  # list of {"path": str (repo-relative), "method": str}

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
                components.append({"path": relpath(match), "method": "cargo-workspace"})

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
        include = pkg.get("include") if isinstance(pkg, dict) else str(pkg)
        if include:
            p = os.path.join(repo_root, include)
            if os.path.isdir(p):
                components.append({"path": relpath(p), "method": "pyproject"})
    project_pkgs = pyproject.get("project", {}).get("packages", [])
    for pkg in project_pkgs:
        include = pkg.get("include") if isinstance(pkg, dict) else str(pkg)
        if include:
            p = os.path.join(repo_root, include)
            if os.path.isdir(p):
                components.append({"path": relpath(p), "method": "pyproject"})

# Step 1c — setup.cfg [options] packages
setup_cfg = os.path.join(repo_root, "setup.cfg")
if os.path.isfile(setup_cfg):
    import configparser
    cfg = configparser.ConfigParser()
    cfg.read(setup_cfg)
    raw = cfg.get("options", "packages", fallback="")
    for pkg in raw.split():
        pkg = pkg.strip().rstrip(",")
        if pkg and pkg != "find:":
            p = os.path.join(repo_root, pkg.replace(".", os.sep))
            if os.path.isdir(p):
                components.append({"path": relpath(p), "method": "setup.cfg"})

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
                components.append({"path": relpath(match), "method": "npm-workspaces"})

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

# If no manifest-based components detected, use fallback dirs as components (no unclaimed)
manifest_found = bool(components)
if not manifest_found:
    components.extend(fallback)
else:
    # Unclaimed = top-level non-denylist dirs not covered by steps 1a-1d
    all_claimed = set(c["path"] for c in components)
    for item in fallback:
        if item["path"] not in all_claimed:
            unclaimed.append(item["path"])

# Step 1f — append --component <path> extras
for extra_path in extra_components:
    rel = relpath(os.path.join(repo_root, extra_path)) if not os.path.isabs(extra_path) else relpath(extra_path)
    if rel not in set(c["path"] for c in components):
        components.append({"path": rel, "method": "manual"})

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

Run the script:

```bash
DETECT_RESULT="$(python3 - "$REPO_ROOT" "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' ${EXTRA_COMPONENTS[@]+"${EXTRA_COMPONENTS[@]}"})" <<'PYEOF'
<inline script above>
PYEOF
)"
```

In practice, emit the Python block as a heredoc script and capture its JSON output. Assign:

```bash
COMPONENTS_JSON="$DETECT_RESULT"
```

### Step 2 — Slug collision detection and disambiguation

Parse `COMPONENTS_JSON`. Extract the `components` array. Group by `slug`. For each group with more than one entry, that is a **collision**.

For each colliding pair (process pairs in alphabetical order by path):

Present an `AskUserQuestion` per collision:

> Two components share the slug `<slug>`: `<path-A>` and `<path-B>`.
> Please choose a suffix to disambiguate. Options:
> 1. Keep `<slug>` for `<path-A>`, rename `<path-B>` to `<slug>-2`
> 2. Keep `<slug>` for `<path-B>`, rename `<path-A>` to `<slug>-1`
> 3. Enter custom slugs for both (provide as `<slug-A> <slug-B>`)

Apply the user's choice, updating the `slug` field for the affected entries. Repeat until no collisions remain.

**This collision-resolution loop runs before writing COMPONENTS.md.**

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
    subprocess.run(["bash", script, run, "component_detected", payload], check=False)
PYEOF
```

### Step 5 — Push-notify + AskUser gate

Push-notify the user that decomposition is ready.

Present `AskUserQuestion`:

> Decomposition complete. Review `$Z_HARNESS_PLAN_DIR/COMPONENTS.md` — it lists N component(s) detected via [methods].
>
> How would you like to proceed?
> 1. Proceed — confirm the detected components and continue to Phase 2
> 2. Abort — to revise the decomposition, edit `COMPONENTS.md` (or re-invoke with `--components=<file>` / `--component <path>`), then re-invoke `/z-uplift`

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

**Full implementation lands in T003 — this is a placeholder describing the expected behavior.**

If `CROSS_CUTTING_SKIP=true`, skip this phase entirely.

Dispatch `consultant-primary` and `consultant-secondary` in parallel on a curated source map (top-50 files by churn over last 90 days, plus each component's entry file) and STYLE.md (if present and `NO_STYLE` is not set). Agents are resolved at dispatch via `scripts/resolve-provider.sh` — do not hardcode provider labels.

Merge findings into `CROSS-CUTTING.md` with three-tier classification:
- `global-task` — cross-component issues needing a dedicated plan
- `per-component-context` — issues that inform per-component audits
- `risk` — watch items with no immediately actionable fix

If any `global-task` findings exist, create a synthetic component named `<slug>-cross-cutting` and insert it FIRST in MANIFEST.

Emit `cross_cutting_classified` telemetry: `{global_tasks, per_component_context, risks}`.

Checkpoint: `phase2-cross-cutting.md`.

---

## Phase 3 — Per-component audits

**Full implementation lands in T004 — this is a placeholder describing the expected behavior.**

For each component in MANIFEST `pending` state (processing synthetic `<slug>-cross-cutting` first if it exists):

1. Mark MANIFEST state `[~] auditing` immediately before dispatch.
2. Dispatch one `auditor` subagent per `--dimensions` value in parallel. Inject `rubric_path` (absolute path of `./STYLE.md`) for `cleanliness` and `design` dimensions when STYLE.md is present and `NO_STYLE` is not set. Inject `cross_cutting_context` from CROSS-CUTTING.md entries matching this component's MANIFEST slug (exact match).
3. Merge per-dimension findings into `<slug>-<component>/REPORT.md`.
4. Dispatch bundled `consultant-primary` + `consultant-secondary` consult in parallel on REPORT.md (drops + additions).
5. Auto-bail check: if `>10 CRIT-HIGH` OR `>30 total` findings → mark MANIFEST `[!] bailed: crit_high_volume`; run `git grep -l "<component-basename>"` across other components; append "Potential dependents (text-grep — incomplete; validate manually for critical APIs)" to REPORT.md and MANIFEST.md; skip TASKS.md generation; continue to next component.
6. Otherwise: promote findings to `<slug>-<component>/TASKS.md`; write minimal SPEC.md + PLAN.md.
7. Dispatch one `reviewer` over generated TASKS.md (mandatory safety gate). On Blocker, re-edit in-place.
8. Mark MANIFEST state `[a] audited`.

Emit `component_audit_start` / `component_audit_done` telemetry per component.

Checkpoint: `phase3-audits.md`.

---

## Phase 4 — Review gate

Present an aggregated queue summary to the user before any implementation begins:

```
Uplift queue summary for <slug>:
  Components audited:   N
  Total tasks queued:   N
  Bailed components:    N (list)
  Dep warnings:         N

Proceed to sequential implementation? [yes / abort]
```

Use `AskUserQuestion` for this gate. If user aborts, emit `run_end status: aborted_by_user` and exit.

Checkpoint: `phase4-review-gate.md`.

---

## Phase 5 — Sequential implement

**Full implementation lands in T005 — this is a placeholder describing the expected behavior.**

For each component with state `[a] audited` in MANIFEST order (synthetic `<slug>-cross-cutting` first):

1. AskUser gate: proceed with this component / skip this component / abort uplift.
2. If proceed: mark MANIFEST `[i] implementing`; invoke `/z-implement-all --tasks=z-harness/plans/<slug>-<component>/TASKS.md`; wait for completion; mark MANIFEST `[x] done`.
3. If skip: mark MANIFEST `[s] skipped: user`; continue to next component.
4. If abort: leave remaining component states unchanged; emit `run_end status: aborted_by_user`; exit.

On re-invoke with a component in `[i] implementing` state (interrupted mid-implement): AskUser — resume with `/z-implement-all` on this component / mark `[s] skipped` / mark `[x] done` (if completed manually) / abort.

Emit `component_implement_start` / `component_implement_done` telemetry per component.

Checkpoint: `phase5-implement.md`.

---

## Phase 6 — Finalize

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

Checkpoint: `phase6-finalize.md`.
