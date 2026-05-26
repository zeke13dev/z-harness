You are reviewing code that Claude just wrote for task T003: Implement Phase 2 (cross-cutting pass): consultant dispatch + 3-tier classification.

Spec (excerpt):
From SPEC.md Phase 2 (lines 97-116):

Dispatch shape (bare agent names — providers are resolved at dispatch by `scripts/resolve-provider.sh`, NOT hardcoded to Gemini/Codex):
```
Agent(subagent_type="consultant-primary", description="Cross-cutting (primary) for <slug>",
      prompt="MODE: cross-cutting-uplift\nrepo_root: <abs>\ncomponents: <COMPONENTS.md verbatim>\nsource_map: <top-50 files by churn over last 90 days, plus each component's entry file (heuristic below)>\nAsk: list cross-component issues (duplicated abstractions, style drift, dead code at module boundaries, public-API drift). For each, emit an explicit `component: <slug-from-MANIFEST>` marker, then classify as global-task | per-component-context | risk.")
Agent(subagent_type="consultant-secondary", description="Cross-cutting (secondary) for <slug>", prompt="<same body>")
```

Entry-file heuristic per component: pick the first match, in this order: `README.md` in component root → `src/lib.rs` → `src/main.rs` → `__init__.py` → `package.json` → first non-test source file by lexicographic order → component root path itself.

Merge into `CROSS-CUTTING.md`:
```markdown
# Cross-cutting findings — <slug>
## Global tasks (need dedicated plan)
- G-001 — [HIGH] <subject> — files: a, b, c
## Per-component context (inform audits)
- C-001 — affects <component-name> — <context>
## Risks (watch items)
- R-001 — <subject> — <evidence>
```

If `global-task` count > 0 → synthetic component `<slug>-cross-cutting` inserted at top of MANIFEST. Its TASKS.md is hand-written from `global-task` entries (one task per G-NNN), with `**Files:**` lines aggregating affected paths.

Acceptance criteria:
1. Dispatch shape matches /z-audit Phase 4 (two parallel Agent() calls in one message, subagent_type = bare consultant-primary / consultant-secondary)
2. CROSS-CUTTING.md has the three required sections and each finding carries a component: marker
3. Synthetic plan dir is created at $(dirname $Z_HARNESS_PLAN_DIR)/${Z_HARNESS_SLUG}-cross-cutting only when global-task > 0
4. --cross-cutting=skip short-circuits cleanly

Focus areas (in priority order):
1. **Dispatch shape**: Are the two Agent() calls actually in a single message (parallel) per /z-audit L138-148? If serialized into two separate code blocks, that's wrong.
2. **--cross-cutting=skip short-circuit**: Does the placeholder CROSS-CUTTING.md get written, AND does it skip downstream synthetic-dir logic, AND does it advance correctly to Phase 3?
3. **Synthetic dir gating**: ONLY created when global-task count > 0; not when only per-component-context or risk findings exist.
4. **CROSS_DIR path computation**: must use $(dirname $Z_HARNESS_PLAN_DIR)/${Z_HARNESS_SLUG}-cross-cutting form — verify no regex-replace lurking.
5. **MANIFEST first-row insert**: synthetic component goes to the FIRST row (not appended), so it processes FIRST in Phase 5.
6. **Source map filtering**: git log returns historical paths; deleted files must be filtered out before passing to consultants.
7. **Entry-file heuristic**: README.md → src/lib.rs → src/main.rs → __init__.py → package.json → first non-test source → component root. All 6 levels implemented?
8. **Source map cap**: max ~100 paths after UNION + filter.
9. **CROSS-CUTTING.md unclassified default**: findings without explicit class default to per-component-context (not dropped).
10. **`cross_cutting_classified` telemetry**: emitted with counts.

Diff (primary artifact — focus your scrutiny on what changed):

=== Phase 2 section: z-uplift.md lines 698-999 ===

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

Then skip to Phase 3.

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
    # first non-test source file lexicographically
    try:
        for fname in sorted(os.listdir(abs_comp)):
            if fname.startswith("test") or fname.startswith("_test") or fname.endswith("_test.py"):
                continue
            full = os.path.join(abs_comp, fname)
            if os.path.isfile(full):
                return os.path.relpath(full, repo_root)
    except OSError:
        pass
    # fall back to component root path itself
    return comp_path

entry_paths = []
for c in components:
    ep = entry_file(c["path"], repo_root)
    if ep and os.path.isfile(os.path.join(repo_root, ep)):
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
Number global-task findings G-001, G-002, ... (include affected files). Number per-component-context findings C-001, C-002, .... Number risk findings R-001, R-002, ...."
```

### Step 4 — Dispatch consultants in parallel

Dispatch `consultant-primary` and `consultant-secondary` in a single message (two `Agent(...)` calls):

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

Merge both consultant returns. For any finding missing a classification, default it to `per-component-context`.

Write `$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md`:

```markdown
# Cross-cutting findings — <slug>

## Global tasks (need dedicated plan)
- G-001 — [HIGH] <subject> — component: <slug> — files: a, b, c
...

## Per-component context (inform audits)
- C-001 — component: <slug> — <context>
...

## Risks (watch items)
- R-001 — component: <slug> — <subject> — <evidence>
...
```

Every finding must carry a `component: <slug>` marker. Unclassified findings are placed in the "Per-component context" section.

### Step 6 — Create synthetic cross-cutting plan (if global-task count > 0)

Count `G_COUNT` (number of `G-NNN` entries in CROSS-CUTTING.md).

If `G_COUNT > 0`:

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
        m = re.match(r'-\s+(G-\d+)\s+[—-]+\s+(?:\[.*?\]\s+)?(.*?)(?:\s+[—-]+\s+files?:\s*(.*))?$', line.strip())
        if m:
            gnum    = m.group(1)
            subject = m.group(2).strip() if m.group(2) else line.strip()
            files   = m.group(3).strip() if m.group(3) else ""
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
new_row = f"| [ ] pending | {cross_slug} | (global) | — | — | {cross_dir}/TASKS.md |\n"

# Insert immediately after the header row separator line
content = re.sub(
    r'(\|[-| ]+\|\n)',
    r'\1' + new_row,
    content,
    count=1
)
with open(manifest_path, "w") as f:
    f.write(content)
print(f"inserted {cross_slug} as first row in MANIFEST.md")
PYEOF
```

### Step 7 — Emit telemetry and checkpoint

```bash
G_COUNT="$(grep -c '^- G-' "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" 2>/dev/null || echo 0)"
C_COUNT="$(grep -c '^- C-' "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" 2>/dev/null || echo 0)"
R_COUNT="$(grep -c '^- R-' "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" 2>/dev/null || echo 0)"

bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cross_cutting_classified \
  "$(printf '{"slug":"%s","global_tasks":%d,"per_component_context":%d,"risks":%d}' \
     "$SLUG" "$G_COUNT" "$C_COUNT" "$R_COUNT")"

cp "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase2-cross-cutting.md"
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":2,"name":"cross-cutting","wall_ms":%d,"user_wait_ms":%d}' \
     "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

Scrutinize this code rigorously. Claude is prone to: over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope beyond the spec.

Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, and a suggested fix.

OUTPUT BUDGET — respect strictly:
- Total response under 8000 characters.
- Report blockers and majors only. Skip minors and nits unless a "minor" hides a correctness bug — in which case promote it to major.
- One finding per bullet. Two sentences max per finding (one for the problem, one for the fix).
- No re-stating of code already in the diff. No summaries of what the code does. No restating the spec.

