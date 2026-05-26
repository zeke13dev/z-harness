2026-05-26T04:17:36.294273Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-26T04:17:36.294880Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-26T04:17:36.294886Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-26T04:17:36.294890Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-suggest-memory/SKILL.md: invalid YAML: did not find expected key at line 3 column 35, while parsing a block mapping
2026-05-26T04:17:36.294895Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-26T04:17:36.294898Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-26T04:17:36.294902Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.133.0
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR]
reasoning effort: medium
reasoning summaries: none
session id: 019e6280-9bd3-7232-b712-481315bc6699
--------
user
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


codex
I’ll verify the changed section against the surrounding harness docs and the referenced `/z-audit` dispatch pattern, then report only blocker/major issues.
exec
/bin/zsh -lc "sed -n '130,155p' z-audit.md" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "sed -n '680,1020p' z-uplift.md" in /Users/zeke/dev/z-harness
 exited 1 in 0ms:
sed: z-audit.md: No such file or directory

 exited 1 in 0ms:
sed: z-uplift.md: No such file or directory

exec
/bin/zsh -lc 'rg -n "CROSS_CUTTING_SKIP|cross_cutting|CROSS-CUTTING|Phase 2" z-uplift.md' in /Users/zeke/dev/z-harness
 exited 2 in 0ms:
rg: z-uplift.md: IO error for operation on z-uplift.md: No such file or directory (os error 2)

codex
Those docs aren’t at the repo root, so I’m locating the installed command docs before judging whether this is only an excerpt issue or a real file-path issue.
exec
/bin/zsh -lc "rg --files | rg '("'^|/)z-(uplift|audit)'"\\.md"'$|SPEC'"\\.md"'$|MANIFEST'"\\.md"'$'"'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
commands/z-uplift.md
commands/z-audit.md
exports/agy/prompts/z-audit.md
exports/codex/prompts/z-audit.md
z-harness/plans/portable-harness/SPEC.md
z-harness/plans/portable-harness/archive/20260524T094344Z-portable-harness/SPEC.md
z-harness/plans/tiered-quality-uplift/SPEC.md
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md
z-harness/plans/z-audit-plan/SPEC.md
z-harness/plans/plan-bail-router/SPEC.md
z-harness/plans/memory-self-improve-loop/SPEC.md
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/SPEC.md
z-harness/plans/z-fix-hypothesis-driven/SPEC.md
z-harness/plans/z-fix-hypothesis-driven/archive/20260524T061903Z-z-fix-hypothesis-driven/SPEC.md
z-harness/plans/lookup-subagent/SPEC.md
z-harness/plans/doc-memories/SPEC.md
z-harness/plans/doc-memories/archive/20260523T060110Z-doc-memories/SPEC.md
z-harness/plans/lookup-subagent/archive/20260524T190609Z-lookup-subagent/SPEC.md
z-harness/plans/mr-style-reviewer/SPEC.md
z-harness/plans/brainstorm-and-research/SPEC.md
z-harness/plans/mr-style-reviewer/archive/20260523T194623Z-mr-style-reviewer/SPEC.md
z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/SPEC.md
z-harness/plans/plan-decompose/SPEC.md
z-harness/plans/compaction-cadence/SPEC.md
z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/SPEC.md

exec
/bin/zsh -lc 'rg -n "Phase 2 — Cross-cutting pass|Dispatch consultants|consultant-primary|cross_cutting_classified" .' in /Users/zeke/dev/z-harness
 succeeded in 221ms:
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:192:   "Cross-LLM consult agents are always referenced as consultant-primary and consultant-secondary; code review uses the reviewer agent.",
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:171:diff --git a/exports/agy/.agent/rules/z-harness-consultant-primary.md b/exports/agy/.agent/rules/z-harness-consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:173:--- a/exports/agy/.agent/rules/z-harness-consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:174:+++ b/exports/agy/.agent/rules/z-harness-consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:1431:diff --git a/exports/agy/prompts/consultant-primary.md b/exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:1433:--- a/exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:1434:+++ b/exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:3619:diff --git a/exports/cursor/.cursor/rules/consultant-primary.mdc b/exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:3621:--- a/exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:3622:+++ b/exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:1:diff --git a/exports/agy/.agent/rules/z-harness-consultant-primary.md b/exports/agy/.agent/rules/z-harness-consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:3:--- a/exports/agy/.agent/rules/z-harness-consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:4:+++ b/exports/agy/.agent/rules/z-harness-consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:1261:diff --git a/exports/agy/prompts/consultant-primary.md b/exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:1263:--- a/exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:1264:+++ b/exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:3449:diff --git a/exports/cursor/.cursor/rules/consultant-primary.mdc b/exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:3451:--- a/exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:3452:+++ b/exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:1024:-diff --git a/exports/agy/prompts/consultant-primary.md b/exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:1026:---- a/exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:1027:-+++ b/exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:3212:-diff --git a/exports/cursor/.cursor/rules/consultant-primary.mdc b/exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:3214:---- a/exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:3215:-+++ b/exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:4954:+diff --git a/exports/agy/prompts/consultant-primary.md b/exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:4956:+--- a/exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:4957:++++ b/exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:7169:+diff --git a/exports/cursor/.cursor/rules/consultant-primary.mdc b/exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:7171:+--- a/exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:7172:++++ b/exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:8174:++  subagent_type="consultant-primary",
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:8694:++  subagent_type="consultant-primary",
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:8900:++  subagent_type="consultant-primary",
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:9420:++  subagent_type="consultant-primary",
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:9627:++  subagent_type="consultant-primary",
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:9831:++  subagent_type="consultant-primary",
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:10351:++  subagent_type="consultant-primary",
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:10558:++  subagent_type="consultant-primary",
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:186:diff --git a/exports/agy/.agent/rules/z-harness-consultant-primary.md b/exports/agy/.agent/rules/z-harness-consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:188:--- a/exports/agy/.agent/rules/z-harness-consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:189:+++ b/exports/agy/.agent/rules/z-harness-consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:1446:diff --git a/exports/agy/prompts/consultant-primary.md b/exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:1448:--- a/exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:1449:+++ b/exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:3634:diff --git a/exports/cursor/.cursor/rules/consultant-primary.mdc b/exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:3636:--- a/exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:3637:+++ b/exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:4411:docs/human/agents.md:4:> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/planning-router.md, agents/remote-runner.md, agents/reviewer.md, agents/spec-precheck.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:4412:docs/human/agents.md:10:These agents decompose complex workflows into focused roles: planning (cluster-planner), planning-route disambiguation (planning-router), implementation (implementer), correctness review (reviewer), code quality review (mr-reviewer), spec validation (spec-precheck), complexity routing (complexity-classifier), documentation (doc-fetcher, doc-updater), remote execution (remote-runner), external retrieval (external-lookup), auditing (auditor), and cross-LLM consultation (consultant-primary, consultant-secondary). The consultant and reviewer agents are provider-agnostic proxies: they call `scripts/resolve-provider.sh` to discover which CLI (Codex, Gemini, or another) is registered for each role, then shell out to that CLI. This replaced the earlier hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files.
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:4453:docs/human/skills.md:36:- `agents` — Skills define the exact subagent types, models, and prompt shapes dispatched during runs. The provider-registry agents (`consultant-primary`, `consultant-secondary`, `reviewer`) abstract CLI vendor selection away from skill logic; `planning-router` is an advisory Haiku helper used only when deterministic route signals conflict.
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:4563: M agents/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:4589: M exports/agy/.agent/rules/z-harness-consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:4613: M exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:4648: M exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:4740:agents/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:4766:exports/agy/.agent/rules/z-harness-consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:4790:exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:4825:exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:5637: M exports/agy/.agent/rules/z-harness-consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:5661: M exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:5696: M exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1:diff --git a/exports/agy/.agent/rules/z-harness-consultant-primary.md b/exports/agy/.agent/rules/z-harness-consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3:--- a/exports/agy/.agent/rules/z-harness-consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4:+++ b/exports/agy/.agent/rules/z-harness-consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1279:diff --git a/exports/agy/prompts/consultant-primary.md b/exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1281:--- a/exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1282:+++ b/exports/agy/prompts/consultant-primary.md
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3494:diff --git a/exports/cursor/.cursor/rules/consultant-primary.mdc b/exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3496:--- a/exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3497:+++ b/exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4499:+  subagent_type="consultant-primary",
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5019:+  subagent_type="consultant-primary",
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5225:+  subagent_type="consultant-primary",
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5745:+  subagent_type="consultant-primary",
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5952:+  subagent_type="consultant-primary",
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6156:+  subagent_type="consultant-primary",
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6676:+  subagent_type="consultant-primary",
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6883:+  subagent_type="consultant-primary",
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v3.patch:9:-> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v3.patch:11:+> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/planning-router.md, agents/remote-runner.md, agents/reviewer.md, agents/spec-precheck.md
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v3.patch:19:+These agents decompose complex workflows into focused roles: planning (cluster-planner), planning-route disambiguation (planning-router), implementation (implementer), correctness review (reviewer), code quality review (mr-reviewer), spec validation (spec-precheck), complexity routing (complexity-classifier), documentation (doc-fetcher, doc-updater), remote execution (remote-runner), external retrieval (external-lookup), auditing (auditor), and cross-LLM consultation (consultant-primary, consultant-secondary). The consultant and reviewer agents are provider-agnostic proxies: they call `scripts/resolve-provider.sh` to discover which CLI (Codex, Gemini, or another) is registered for each role, then shell out to that CLI. This replaced the earlier hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files.
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v3.patch:29:-- `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v3.patch:37:+- `agents/consultant-primary.md:1` — `consultant-primary` — Provider-agnostic proxy for the primary consultant LLM (resolved via `scripts/resolve-provider.sh consultant_primary`). Supports 11 modes: `bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `brainstorm`, `research-review`, `doc-audit`, `test-cases`, `mr-review`, `generate-hypotheses-round1`, `generate-hypotheses-round2-adversarial`. Emits `consult_start` before the provider call for liveness detection; uses `scripts/check-timeout.sh` to detect and wrap calls with `timeout(1)` / `gtimeout` when available.
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v3.patch:38:+- `agents/consultant-secondary.md:1` — `consultant-secondary` — Identical shape to consultant-primary but resolves `consultant_secondary` — must be a distinct provider. Same 11 modes.
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v3.patch:43:+- `agents/mr-reviewer.md:1` — `mr-reviewer` — Multi-LLM code-quality reviewer (not correctness); targets AI-shaped slop, defensive bloat, test noise, abstraction failures, style drift. Fans out to `consultant-primary` / `consultant-secondary` voices in parallel, deduplicates findings by `(file, category, normalized_text)`, applies consensus tier-bumps and dismissal-pattern Jaccard matching. Returns fenced JSON + `## Summary` block.
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v3.patch:60:+- `consultant-primary`, `consultant-secondary`, and `reviewer` are provider-agnostic proxy shells (Haiku model) that shell out to an external CLI; the actual reasoning model is whatever `resolve-provider.sh` returns. The old hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files no longer exist — references to them in archived transcripts or old docs are stale.
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v3.patch:61:+- All three proxy agents (`consultant-primary`, `consultant-secondary`, `reviewer`) now source `scripts/check-timeout.sh` before calling the provider CLI. This sets `$TIMEOUT_CMD` and emits a `timeout_availability` event once per run so silent timeouts are debuggable. They also emit a `consult_start` / `review_start` event BEFORE the provider call so `scripts/liveness.sh` can detect hung consultants even when `$TIMEOUT_CMD` is empty.
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v3.patch:72:+- `/z-plan` Phase 3 dispatches `consultant-primary` and `consultant-secondary` in parallel with `MODE: bundled-decisions`; each resolves its provider CLI via `scripts/resolve-provider.sh` and returns a standard wrapper response.
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v3.patch:87:+        "agents/consultant-primary.md",
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v3.patch:203:+    "agents/consultant-primary.md",
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v3.patch:338:+    {"file": "agents/consultant-primary.md", "line": 1, "symbol": "consultant-primary", "kind": "module", "summary": "Haiku proxy; resolves primary consultant provider via resolve-provider.sh; 11 modes; emits consult_start for liveness; uses check-timeout.sh."},
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v3.patch:339:+    {"file": "agents/consultant-secondary.md", "line": 1, "symbol": "consultant-secondary", "kind": "module", "summary": "Haiku proxy; resolves secondary consultant provider (must differ from primary); same 11 modes as consultant-primary."},
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v3.patch:356:+    "consultant-primary, consultant-secondary, and reviewer resolve their provider at runtime via scripts/resolve-provider.sh - they are not hard-coded to any specific LLM.",
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v3.patch:359:+    "consultant-primary, consultant-secondary, and reviewer emit consult_start / review_start BEFORE the provider call so liveness.sh can detect hangs."
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v3.patch:363:+    "codex-consultant.md, codex-reviewer.md, and gemini-consultant.md no longer exist - replaced by consultant-primary.md, consultant-secondary.md, reviewer.md with runtime provider resolution.",
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v1.patch:9:-> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v1.patch:11:+> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/planning-router.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v1.patch:26: - `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:14: -> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:16:-+> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/planning-router.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:17:++> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/planning-router.md, agents/remote-runner.md, agents/reviewer.md, agents/spec-precheck.md
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:29:++These agents decompose complex workflows into focused roles: planning (cluster-planner), planning-route disambiguation (planning-router), implementation (implementer), correctness review (reviewer), code quality review (mr-reviewer), spec validation (spec-precheck), complexity routing (complexity-classifier), documentation (doc-fetcher, doc-updater), remote execution (remote-runner), external retrieval (external-lookup), auditing (auditor), and cross-LLM consultation (consultant-primary, consultant-secondary). The consultant and reviewer agents are provider-agnostic proxies: they call `scripts/resolve-provider.sh` to discover which CLI (Codex, Gemini, or another) is registered for each role, then shell out to that CLI. This replaced the earlier hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files.
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:37:- - `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:45:+-- `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:57:++- `agents/consultant-primary.md:1` — `consultant-primary` — Provider-agnostic proxy for the primary consultant LLM (resolved via `scripts/resolve-provider.sh consultant_primary`). Supports 11 modes: `bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `brainstorm`, `research-review`, `doc-audit`, `test-cases`, `mr-review`, `generate-hypotheses-round1`, `generate-hypotheses-round2-adversarial`. Emits `consult_start` before the provider call for liveness detection; uses `scripts/check-timeout.sh` to detect and wrap calls with `timeout(1)` / `gtimeout` when available.
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:58:++- `agents/consultant-secondary.md:1` — `consultant-secondary` — Identical shape to consultant-primary but resolves `consultant_secondary` — must be a distinct provider. Same 11 modes.
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:63:++- `agents/mr-reviewer.md:1` — `mr-reviewer` — Multi-LLM code-quality reviewer (not correctness); targets AI-shaped slop, defensive bloat, test noise, abstraction failures, style drift. Fans out to `consultant-primary` / `consultant-secondary` voices in parallel, deduplicates findings by `(file, category, normalized_text)`, applies consensus tier-bumps and dismissal-pattern Jaccard matching. Returns fenced JSON + `## Summary` block.
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:82:++- `consultant-primary`, `consultant-secondary`, and `reviewer` are provider-agnostic proxy shells (Haiku model) that shell out to an external CLI; the actual reasoning model is whatever `resolve-provider.sh` returns. The old hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files no longer exist — references to them in archived transcripts or old docs are stale.
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:83:++- All three proxy agents (`consultant-primary`, `consultant-secondary`, `reviewer`) now source `scripts/check-timeout.sh` before calling the provider CLI. This sets `$TIMEOUT_CMD` and emits a `timeout_availability` event once per run so silent timeouts are debuggable. They also emit a `consult_start` / `review_start` event BEFORE the provider call so `scripts/liveness.sh` can detect hung consultants even when `$TIMEOUT_CMD` is empty.
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:96:++- `/z-plan` Phase 3 dispatches `consultant-primary` and `consultant-secondary` in parallel with `MODE: bundled-decisions`; each resolves its provider CLI via `scripts/resolve-provider.sh` and returns a standard wrapper response.
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:113:++        "agents/consultant-primary.md",
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:205:++    "agents/consultant-primary.md",
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:356:++    {"file": "agents/consultant-primary.md", "line": 1, "symbol": "consultant-primary", "kind": "module", "summary": "Haiku proxy; resolves primary consultant provider via resolve-provider.sh; 11 modes; emits consult_start for liveness; uses check-timeout.sh."},
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:357:++    {"file": "agents/consultant-secondary.md", "line": 1, "symbol": "consultant-secondary", "kind": "module", "summary": "Haiku proxy; resolves secondary consultant provider (must differ from primary); same 11 modes as consultant-primary."},
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:374:++    "consultant-primary, consultant-secondary, and reviewer resolve their provider at runtime via scripts/resolve-provider.sh - they are not hard-coded to any specific LLM.",
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:377:++    "consultant-primary, consultant-secondary, and reviewer emit consult_start / review_start BEFORE the provider call so liveness.sh can detect hangs."
./z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch:381:++    "codex-consultant.md, codex-reviewer.md, and gemini-consultant.md no longer exist - replaced by consultant-primary.md, consultant-secondary.md, reviewer.md with runtime provider resolution.",
./z-harness/archive/portable-harness/transcripts/001-codex-plan-review.response.md:3:**Provider invariant conflict:** `SPEC.md:190` only requires `consultant-primary` and `consultant-secondary` to be distinct, but `SPEC.md:82` shows both resolving to codex while `reviewer=codex`. The invariant as stated contradicts the example. Clarify: are all three roles required distinct, or only the two consultants?
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:9:-> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:11:+> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/planning-router.md, agents/remote-runner.md, agents/reviewer.md, agents/spec-precheck.md
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:19:+These agents decompose complex workflows into focused roles: planning (cluster-planner), planning-route disambiguation (planning-router), implementation (implementer), correctness review (reviewer), code quality review (mr-reviewer), spec validation (spec-precheck), complexity routing (complexity-classifier), documentation (doc-fetcher, doc-updater), remote execution (remote-runner), external retrieval (external-lookup), auditing (auditor), and cross-LLM consultation (consultant-primary, consultant-secondary). The consultant and reviewer agents are provider-agnostic proxies: they call `scripts/resolve-provider.sh` to discover which CLI (Codex, Gemini, or another) is registered for each role, then shell out to that CLI. This replaced the earlier hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files.
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:29:-- `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:37:+- `agents/consultant-primary.md:1` — `consultant-primary` — Provider-agnostic proxy for the primary consultant LLM (resolved via `scripts/resolve-provider.sh consultant_primary`). Supports 11 modes: `bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `brainstorm`, `research-review`, `doc-audit`, `test-cases`, `mr-review`, `generate-hypotheses-round1`, `generate-hypotheses-round2-adversarial`. Emits `consult_start` before the provider call for liveness detection; uses `scripts/check-timeout.sh` to detect and wrap calls with `timeout(1)` / `gtimeout` when available.
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:38:+- `agents/consultant-secondary.md:1` — `consultant-secondary` — Identical shape to consultant-primary but resolves `consultant_secondary` — must be a distinct provider. Same 11 modes.
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:43:+- `agents/mr-reviewer.md:1` — `mr-reviewer` — Multi-LLM code-quality reviewer (not correctness); targets AI-shaped slop, defensive bloat, test noise, abstraction failures, style drift. Fans out to `consultant-primary` / `consultant-secondary` voices in parallel, deduplicates findings by `(file, category, normalized_text)`, applies consensus tier-bumps and dismissal-pattern Jaccard matching. Returns fenced JSON + `## Summary` block.
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:60:+- `consultant-primary`, `consultant-secondary`, and `reviewer` are provider-agnostic proxy shells (Haiku model) that shell out to an external CLI; the actual reasoning model is whatever `resolve-provider.sh` returns. The old hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files no longer exist — references to them in archived transcripts or old docs are stale.
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:61:+- All three proxy agents (`consultant-primary`, `consultant-secondary`, `reviewer`) now source `scripts/check-timeout.sh` before calling the provider CLI. This sets `$TIMEOUT_CMD` and emits a `timeout_availability` event once per run so silent timeouts are debuggable. They also emit a `consult_start` / `review_start` event BEFORE the provider call so `scripts/liveness.sh` can detect hung consultants even when `$TIMEOUT_CMD` is empty.
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:72:+- `/z-plan` Phase 3 dispatches `consultant-primary` and `consultant-secondary` in parallel with `MODE: bundled-decisions`; each resolves its provider CLI via `scripts/resolve-provider.sh` and returns a standard wrapper response.
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:87:+        "agents/consultant-primary.md",
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:203:+    "agents/consultant-primary.md",
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:338:+    {"file": "agents/consultant-primary.md", "line": 1, "symbol": "consultant-primary", "kind": "module", "summary": "Haiku proxy; resolves primary consultant provider via resolve-provider.sh; 11 modes; emits consult_start for liveness; uses check-timeout.sh."},
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:339:+    {"file": "agents/consultant-secondary.md", "line": 1, "symbol": "consultant-secondary", "kind": "module", "summary": "Haiku proxy; resolves secondary consultant provider (must differ from primary); same 11 modes as consultant-primary."},
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:356:+    "consultant-primary, consultant-secondary, and reviewer resolve their provider at runtime via scripts/resolve-provider.sh - they are not hard-coded to any specific LLM.",
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:359:+    "consultant-primary, consultant-secondary, and reviewer emit consult_start / review_start BEFORE the provider call so liveness.sh can detect hangs."
./z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch:363:+    "codex-consultant.md, codex-reviewer.md, and gemini-consultant.md no longer exist - replaced by consultant-primary.md, consultant-secondary.md, reviewer.md with runtime provider resolution.",
./z-harness/archive/portable-harness/transcripts/001-codex-plan-review.prompt.md:4:See above — file covers: plan-layout migration, provider registry (hybrid config, 3 roles, CLI-only kind), role-named agent files (consultant-primary, consultant-secondary, reviewer), multi-IDE export (Cursor, Codex, Agy with per-target CAPABILITIES.md), symlink + tarball install + /z-update, and docs updates.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:692:    {"file": "skills/z-brainstorm/SKILL.md", "line": 1, "symbol": "z-brainstorm", "kind": "module", "summary": "Three-vendor parallel ideation (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check; produces BRAINSTORM.md."},
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:713:    "Cross-LLM consult agents are always referenced as consultant-primary and consultant-secondary; code review uses the reviewer agent.",
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:740:All skills share a common set of infrastructure assumptions established in the 2026-05-24 portable-harness migration: plan artifacts are resolved via `scripts/plan-path.sh` to `$Z_HARNESS_PLAN_DIR` (rather than hardcoded `z-harness/<slug>/` paths), cross-LLM consults use the provider-registry agents `consultant-primary` and `consultant-secondary`, and code review uses the `reviewer` agent. These agent names are stable identifiers that map to actual CLI vendors through the provider registry — skills never reference `gemini-consultant`, `codex-consultant`, or `codex-reviewer` directly.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:745:- `skills/z-brainstorm/SKILL.md:1` — `z-brainstorm` — Parallel pre-plan ideation: three vendor-diverse ideators (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check, producing BRAINSTORM.md with `chosen_framing`.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:765:- `agents` — Skills define the exact subagent types, models, and prompt shapes dispatched during runs. The provider-registry agents (`consultant-primary`, `consultant-secondary`, `reviewer`) abstract CLI vendor selection away from skill logic.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:707:    {"file": "skills/z-brainstorm/SKILL.md", "line": 1, "symbol": "z-brainstorm", "kind": "module", "summary": "Three-vendor parallel ideation (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check; produces BRAINSTORM.md."},
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:728:    "Cross-LLM consult agents are always referenced as consultant-primary and consultant-secondary; code review uses the reviewer agent.",
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:755:All skills share a common set of infrastructure assumptions established in the 2026-05-24 portable-harness migration: plan artifacts are resolved via `scripts/plan-path.sh` to `$Z_HARNESS_PLAN_DIR` (rather than hardcoded `z-harness/<slug>/` paths), cross-LLM consults use the provider-registry agents `consultant-primary` and `consultant-secondary`, and code review uses the `reviewer` agent. These agent names are stable identifiers that map to actual CLI vendors through the provider registry — skills never reference `gemini-consultant`, `codex-consultant`, or `codex-reviewer` directly.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:760:- `skills/z-brainstorm/SKILL.md:1` — `z-brainstorm` — Parallel pre-plan ideation: three vendor-diverse ideators (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check, producing BRAINSTORM.md with `chosen_framing`.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:780:- `agents` — Skills define the exact subagent types, models, and prompt shapes dispatched during runs. The provider-registry agents (`consultant-primary`, `consultant-secondary`, `reviewer`) abstract CLI vendor selection away from skill logic.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:1483:   102	  subagent_type="consultant-primary",
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:1604:   101	  subagent_type="consultant-primary",
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:9:-> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:11:+> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/planning-router.md, agents/remote-runner.md, agents/reviewer.md, agents/spec-precheck.md
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:19:+These agents decompose complex workflows into focused roles: planning (cluster-planner), planning-route disambiguation (planning-router), implementation (implementer), correctness review (reviewer), code quality review (mr-reviewer), spec validation (spec-precheck), complexity routing (complexity-classifier), documentation (doc-fetcher, doc-updater), remote execution (remote-runner), external retrieval (external-lookup), auditing (auditor), and cross-LLM consultation (consultant-primary, consultant-secondary). The consultant and reviewer agents are provider-agnostic proxies: they call `scripts/resolve-provider.sh` to discover which CLI (Codex, Gemini, or another) is registered for each role, then shell out to that CLI. This replaced the earlier hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files.
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:29:-- `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:37:+- `agents/consultant-primary.md:1` — `consultant-primary` — Provider-agnostic proxy for the primary consultant LLM (resolved via `scripts/resolve-provider.sh consultant_primary`). Supports 11 modes: `bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `brainstorm`, `research-review`, `doc-audit`, `test-cases`, `mr-review`, `generate-hypotheses-round1`, `generate-hypotheses-round2-adversarial`. Emits `consult_start` before the provider call for liveness detection; uses `scripts/check-timeout.sh` to detect and wrap calls with `timeout(1)` / `gtimeout` when available.
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:38:+- `agents/consultant-secondary.md:1` — `consultant-secondary` — Identical shape to consultant-primary but resolves `consultant_secondary` — must be a distinct provider. Same 11 modes.
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:43:+- `agents/mr-reviewer.md:1` — `mr-reviewer` — Multi-LLM code-quality reviewer (not correctness); targets AI-shaped slop, defensive bloat, test noise, abstraction failures, style drift. Fans out to `consultant-primary` / `consultant-secondary` voices in parallel, deduplicates findings by `(file, category, normalized_text)`, applies consensus tier-bumps and dismissal-pattern Jaccard matching. Returns fenced JSON + `## Summary` block.
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:62:+- `consultant-primary`, `consultant-secondary`, and `reviewer` are provider-agnostic proxy shells (Haiku model) that shell out to an external CLI; the actual reasoning model is whatever `resolve-provider.sh` returns. The old hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files no longer exist — references to them in archived transcripts or old docs are stale.
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:63:+- All three proxy agents (`consultant-primary`, `consultant-secondary`, `reviewer`) now source `scripts/check-timeout.sh` before calling the provider CLI. This sets `$TIMEOUT_CMD` and emits a `timeout_availability` event once per run so silent timeouts are debuggable. They also emit a `consult_start` / `review_start` event BEFORE the provider call so `scripts/liveness.sh` can detect hung consultants even when `$TIMEOUT_CMD` is empty.
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:75:+- `/z-plan` Phase 3 dispatches `consultant-primary` and `consultant-secondary` in parallel with `MODE: bundled-decisions`; each resolves its provider CLI via `scripts/resolve-provider.sh` and returns a standard wrapper response.
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:147:+All skills share a common set of infrastructure assumptions established in the 2026-05-24 portable-harness migration: plan artifacts are resolved via `scripts/plan-path.sh` to `$Z_HARNESS_PLAN_DIR` (rather than hardcoded `z-harness/<slug>/` paths), cross-LLM consults use the provider-registry agents `consultant-primary` and `consultant-secondary`, and code review uses the `reviewer` agent. These agent names are stable identifiers that map to actual CLI vendors through the provider registry — skills never reference `gemini-consultant`, `codex-consultant`, or `codex-reviewer` directly.
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:170:+- `skills/z-brainstorm/SKILL.md:1` — `z-brainstorm` — Parallel pre-plan ideation: three vendor-diverse ideators (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check, producing BRAINSTORM.md with `chosen_framing`.
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:193:+- `agents` — Skills define the exact subagent types, models, and prompt shapes dispatched during runs. The provider-registry agents (`consultant-primary`, `consultant-secondary`, `reviewer`) abstract CLI vendor selection away from skill logic; `planning-router` is an advisory Haiku helper used only when deterministic route signals conflict.
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:230:+        "agents/consultant-primary.md",
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:361:+    "agents/consultant-primary.md",
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:496:+    {"file": "agents/consultant-primary.md", "line": 1, "symbol": "consultant-primary", "kind": "module", "summary": "Haiku proxy; resolves primary consultant provider via resolve-provider.sh; 11 modes; emits consult_start for liveness; uses check-timeout.sh."},
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:497:+    {"file": "agents/consultant-secondary.md", "line": 1, "symbol": "consultant-secondary", "kind": "module", "summary": "Haiku proxy; resolves secondary consultant provider (must differ from primary); same 11 modes as consultant-primary."},
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:514:+    "consultant-primary, consultant-secondary, and reviewer resolve their provider at runtime via scripts/resolve-provider.sh - they are not hard-coded to any specific LLM.",
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:517:+    "consultant-primary, consultant-secondary, and reviewer emit consult_start / review_start BEFORE the provider call so liveness.sh can detect hangs.",
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:522:+    "codex-consultant.md, codex-reviewer.md, and gemini-consultant.md no longer exist - replaced by consultant-primary.md, consultant-secondary.md, reviewer.md with runtime provider resolution.",
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:750:+    {"file": "skills/z-brainstorm/SKILL.md", "line": 1, "symbol": "z-brainstorm", "kind": "module", "summary": "Three-vendor parallel ideation (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check; produces BRAINSTORM.md."},
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:773:+    "Cross-LLM consult agents are always referenced as consultant-primary and consultant-secondary; code review uses the reviewer agent.",
./z-harness/archive/compaction-cadence/transcripts/001-codex-light-fix.prompt.md:36:- `consultant-primary` reads SPEC.md + PLAN.md + TASKS.md + cumulative.diff + docs/llm/*.json in one go.
./z-harness/archive/portable-harness-plan-review/transcripts/001-plan-review-portable-harness.prompt.md:10:5. Three stable agent files: `consultant-primary.md`, `consultant-secondary.md`, `reviewer.md` (provider-agnostic via role names)
./z-harness/archive/portable-harness-plan-review/transcripts/001-plan-review-portable-harness.prompt.md:20:DRY/KISS/SOLID checks all present. Edge cases listed: no providers.json, unbound roles, missing CLI on PATH, Z_HARNESS_PLANS_DIR override, /z-update with uncommitted changes, export filters, consultant-primary/secondary must be distinct.
./z-harness/archive/portable-harness-plan-review/transcripts/001-plan-review-portable-harness.response.md:18:- Missing distinct-provider invariant enforcement: SPEC (line 190) forbids `consultant-primary` and `consultant-secondary` from resolving to the same provider. PLAN Phase 3 completely omits the pre-flight check in `resolve-provider.sh`.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/agents.llm.json:9:    "agents/consultant-primary.md",
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/agents.llm.json:26:    {"file": "agents/consultant-primary.md", "line": 1, "symbol": "consultant-primary", "kind": "module", "summary": "Haiku proxy; resolves primary consultant provider via resolve-provider.sh; 11 modes; emits consult_start for liveness; uses check-timeout.sh."},
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/agents.llm.json:27:    {"file": "agents/consultant-secondary.md", "line": 1, "symbol": "consultant-secondary", "kind": "module", "summary": "Haiku proxy; resolves secondary consultant provider (must differ from primary); same 11 modes as consultant-primary."},
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/agents.llm.json:42:    "consultant-primary, consultant-secondary, and reviewer resolve their provider at runtime via scripts/resolve-provider.sh - they are not hard-coded to any specific LLM.",
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/agents.llm.json:45:    "consultant-primary, consultant-secondary, and reviewer emit consult_start / review_start BEFORE the provider call so liveness.sh can detect hangs.",
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/agents.llm.json:51:    "codex-consultant.md, codex-reviewer.md, and gemini-consultant.md no longer exist - replaced by consultant-primary.md, consultant-secondary.md, reviewer.md with runtime provider resolution.",
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.llm.json:29:    {"file": "skills/z-brainstorm/SKILL.md", "line": 1, "symbol": "z-brainstorm", "kind": "module", "summary": "Three-vendor parallel ideation (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check; produces BRAINSTORM.md."},
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.llm.json:50:    "Cross-LLM consult agents are always referenced as consultant-primary and consultant-secondary; code review uses the reviewer agent.",
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:366:   197	  subagent_type="consultant-primary",
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/agents.human.md:4:> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/planning-router.md, agents/remote-runner.md, agents/reviewer.md, agents/spec-precheck.md
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/agents.human.md:10:These agents decompose complex workflows into focused roles: planning (cluster-planner), planning-route disambiguation (planning-router), implementation (implementer), correctness review (reviewer), code quality review (mr-reviewer), spec validation (spec-precheck), complexity routing (complexity-classifier), documentation (doc-fetcher, doc-updater), remote execution (remote-runner), external retrieval (external-lookup), auditing (auditor), and cross-LLM consultation (consultant-primary, consultant-secondary). The consultant and reviewer agents are provider-agnostic proxies: they call `scripts/resolve-provider.sh` to discover which CLI (Codex, Gemini, or another) is registered for each role, then shell out to that CLI. This replaced the earlier hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/agents.human.md:17:- `agents/consultant-primary.md:1` — `consultant-primary` — Provider-agnostic proxy for the primary consultant LLM (resolved via `scripts/resolve-provider.sh consultant_primary`). Supports 11 modes: `bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `brainstorm`, `research-review`, `doc-audit`, `test-cases`, `mr-review`, `generate-hypotheses-round1`, `generate-hypotheses-round2-adversarial`. Emits `consult_start` before the provider call for liveness detection; uses `scripts/check-timeout.sh` to detect and wrap calls with `timeout(1)` / `gtimeout` when available.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/agents.human.md:18:- `agents/consultant-secondary.md:1` — `consultant-secondary` — Identical shape to consultant-primary but resolves `consultant_secondary` — must be a distinct provider. Same 11 modes.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/agents.human.md:23:- `agents/mr-reviewer.md:1` — `mr-reviewer` — Multi-LLM code-quality reviewer (not correctness); targets AI-shaped slop, defensive bloat, test noise, abstraction failures, style drift. Fans out to `consultant-primary` / `consultant-secondary` voices in parallel, deduplicates findings by `(file, category, normalized_text)`, applies consensus tier-bumps and dismissal-pattern Jaccard matching. Returns fenced JSON + `## Summary` block.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/agents.human.md:39:- `consultant-primary`, `consultant-secondary`, and `reviewer` are provider-agnostic proxy shells (Haiku model) that shell out to an external CLI; the actual reasoning model is whatever `resolve-provider.sh` returns. The old hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files no longer exist — references to them in archived transcripts or old docs are stale.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/agents.human.md:40:- All three proxy agents (`consultant-primary`, `consultant-secondary`, `reviewer`) now source `scripts/check-timeout.sh` before calling the provider CLI. This sets `$TIMEOUT_CMD` and emits a `timeout_availability` event once per run so silent timeouts are debuggable. They also emit a `consult_start` / `review_start` event BEFORE the provider call so `scripts/liveness.sh` can detect hung consultants even when `$TIMEOUT_CMD` is empty.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/agents.human.md:52:- `/z-plan` Phase 3 dispatches `consultant-primary` and `consultant-secondary` in parallel with `MODE: bundled-decisions`; each resolves its provider CLI via `scripts/resolve-provider.sh` and returns a standard wrapper response.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.human.md:10:All skills share a common set of infrastructure assumptions established in the 2026-05-24 portable-harness migration: plan artifacts are resolved via `scripts/plan-path.sh` to `$Z_HARNESS_PLAN_DIR` (rather than hardcoded `z-harness/<slug>/` paths), cross-LLM consults use the provider-registry agents `consultant-primary` and `consultant-secondary`, and code review uses the `reviewer` agent. These agent names are stable identifiers that map to actual CLI vendors through the provider registry — skills never reference `gemini-consultant`, `codex-consultant`, or `codex-reviewer` directly.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.human.md:16:- `skills/z-brainstorm/SKILL.md:1` — `z-brainstorm` — Parallel pre-plan ideation: three vendor-diverse ideators (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check, producing BRAINSTORM.md with `chosen_framing`.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.human.md:36:- `agents` — Skills define the exact subagent types, models, and prompt shapes dispatched during runs. The provider-registry agents (`consultant-primary`, `consultant-secondary`, `reviewer`) abstract CLI vendor selection away from skill logic; `planning-router` is an advisory Haiku helper used only when deterministic route signals conflict.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.human.diff:8: > Covers source: agents/auditor.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/planning-router.md, agents/remote-runner.md, agents/reviewer.md, agents/spec-precheck.md
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.human.diff:15:-These agents decompose complex workflows into focused roles: planning (cluster-planner), planning-route disambiguation (planning-router), implementation (implementer), correctness review (reviewer), code quality review (mr-reviewer), spec validation (spec-precheck), complexity routing (complexity-classifier), documentation (doc-fetcher, doc-updater), remote execution (remote-runner), external retrieval (external-lookup), auditing (auditor), and cross-LLM consultation (consultant-primary, consultant-secondary). The consultant and reviewer agents are provider-agnostic proxies: they call `scripts/resolve-provider.sh` to discover which CLI (Codex, Gemini, or another) is registered for each role, then shell out to that CLI. This replaced the earlier hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.human.diff:16:+The suite is split by responsibility: planning route advice (`planning-router`), cluster planning (`cluster-planner`), complexity stamping (`complexity-classifier`), implementation (`implementer`), correctness review (`reviewer`), code-quality review (`mr-reviewer`), spec validation (`spec-precheck`), documentation (`doc-fetcher`, `doc-updater`), external lookup (`external-lookup`), remote verification (`remote-runner`), auditing (`auditor`), and cross-LLM consultation (`consultant-primary`, `consultant-secondary`). The consultant and reviewer proxy agents resolve provider CLIs at runtime through `scripts/resolve-provider.sh`; the concrete provider is not hard-coded in the agent prompt.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.human.diff:23:-- `agents/consultant-primary.md:1` — `consultant-primary` — Provider-agnostic proxy for the primary consultant LLM (resolved via `scripts/resolve-provider.sh consultant_primary`). Supports 11 modes: `bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `brainstorm`, `research-review`, `doc-audit`, `test-cases`, `mr-review`, `generate-hypotheses-round1`, `generate-hypotheses-round2-adversarial`. Emits `consult_start` before the provider call for liveness detection; uses `scripts/check-timeout.sh` to detect and wrap calls with `timeout(1)` / `gtimeout` when available.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.human.diff:24:-- `agents/consultant-secondary.md:1` — `consultant-secondary` — Identical shape to consultant-primary but resolves `consultant_secondary` — must be a distinct provider. Same 11 modes.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.human.diff:29:-- `agents/mr-reviewer.md:1` — `mr-reviewer` — Multi-LLM code-quality reviewer (not correctness); targets AI-shaped slop, defensive bloat, test noise, abstraction failures, style drift. Fans out to `consultant-primary` / `consultant-secondary` voices in parallel, deduplicates findings by `(file, category, normalized_text)`, applies consensus tier-bumps and dismissal-pattern Jaccard matching. Returns fenced JSON + `## Summary` block.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.human.diff:37:+- `agents/consultant-primary.md:1` — `consultant-primary` — Provider-agnostic primary consultant proxy; supports planning, review, debug, brainstorm, research, docs, test, and MR-review modes.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.human.diff:63:-- `consultant-primary`, `consultant-secondary`, and `reviewer` are provider-agnostic proxy shells (Haiku model) that shell out to an external CLI; the actual reasoning model is whatever `resolve-provider.sh` returns. The old hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files no longer exist — references to them in archived transcripts or old docs are stale.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.human.diff:64:-- All three proxy agents (`consultant-primary`, `consultant-secondary`, `reviewer`) now source `scripts/check-timeout.sh` before calling the provider CLI. This sets `$TIMEOUT_CMD` and emits a `timeout_availability` event once per run so silent timeouts are debuggable. They also emit a `consult_start` / `review_start` event BEFORE the provider call so `scripts/liveness.sh` can detect hung consultants even when `$TIMEOUT_CMD` is empty.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.human.diff:72:+- `consultant-primary`, `consultant-secondary`, and `reviewer` are Haiku proxy prompts that shell out to provider CLIs resolved at runtime. Old hard-coded `codex-consultant.md`, `gemini-consultant.md`, and `codex-reviewer.md` references are stale.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.human.diff:84:-- `/z-plan` Phase 3 dispatches `consultant-primary` and `consultant-secondary` in parallel with `MODE: bundled-decisions`; each resolves its provider CLI via `scripts/resolve-provider.sh` and returns a standard wrapper response.
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/exports.stat:1: .../.agent/rules/z-harness-consultant-primary.md   |  20 +-
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/exports.stat:27: exports/agy/prompts/consultant-primary.md          |  20 +-
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/exports.stat:65: .../cursor/.cursor/rules/consultant-primary.mdc    |  20 +-
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.llm.diff:18:-    {"file": "agents/consultant-primary.md", "line": 1, "symbol": "consultant-primary", "kind": "module", "summary": "Haiku proxy; resolves primary consultant provider via resolve-provider.sh; 11 modes; emits consult_start for liveness; uses check-timeout.sh."},
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.llm.diff:19:-    {"file": "agents/consultant-secondary.md", "line": 1, "symbol": "consultant-secondary", "kind": "module", "summary": "Haiku proxy; resolves secondary consultant provider (must differ from primary); same 11 modes as consultant-primary."},
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.llm.diff:32:+    {"file": "agents/consultant-primary.md", "line": 1, "symbol": "consultant-primary", "kind": "module", "summary": "Primary provider proxy for consult/review modes."},
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.llm.diff:48:-    "consultant-primary, consultant-secondary, and reviewer resolve their provider at runtime via scripts/resolve-provider.sh - they are not hard-coded to any specific LLM.",
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.llm.diff:51:-    "consultant-primary, consultant-secondary, and reviewer emit consult_start / review_start BEFORE the provider call so liveness.sh can detect hangs.",
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.llm.diff:55:+    "consultant-primary, consultant-secondary, and reviewer resolve providers via scripts/resolve-provider.sh.",
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/agents.llm.diff:65:-    "codex-consultant.md, codex-reviewer.md, and gemini-consultant.md no longer exist - replaced by consultant-primary.md, consultant-secondary.md, reviewer.md with runtime provider resolution.",
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.llm.diff:19:-    {"file": "skills/z-brainstorm/SKILL.md", "line": 1, "symbol": "z-brainstorm", "kind": "module", "summary": "Three-vendor parallel ideation (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check; produces BRAINSTORM.md."},
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.llm.diff:60:-    "Cross-LLM consult agents are always referenced as consultant-primary and consultant-secondary; code review uses the reviewer agent.",
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.llm.diff:69:+    "Consults use consultant-primary/secondary; review uses reviewer.",
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.human.diff:15:-All skills share a common set of infrastructure assumptions established in the 2026-05-24 portable-harness migration: plan artifacts are resolved via `scripts/plan-path.sh` to `$Z_HARNESS_PLAN_DIR` (rather than hardcoded `z-harness/<slug>/` paths), cross-LLM consults use the provider-registry agents `consultant-primary` and `consultant-secondary`, and code review uses the `reviewer` agent. These agent names are stable identifiers that map to actual CLI vendors through the provider registry — skills never reference `gemini-consultant`, `codex-consultant`, or `codex-reviewer` directly.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.human.diff:16:+The current skill family has converged on a shared route-policy model. Planning and execution skills collect deterministic signals, call the advisory `planning-router` only when those signals conflict, write `route-decision.md`, emit `plan_route_decision`, preserve command-specific telemetry, present an AskUser handoff, and stop rather than auto-running the recommended target. The skills also assume the provider-registry agent names (`consultant-primary`, `consultant-secondary`, `reviewer`), shared scripts for path resolution and logging, and docs/memory maintenance through `doc-updater`, `/z-maintain-docs`, and `/z-suggest-memory`.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.human.diff:22:-- `skills/z-brainstorm/SKILL.md:1` — `z-brainstorm` — Parallel pre-plan ideation: three vendor-diverse ideators (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check, producing BRAINSTORM.md with `chosen_framing`.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.human.diff:60:-- `agents` — Skills define the exact subagent types, models, and prompt shapes dispatched during runs. The provider-registry agents (`consultant-primary`, `consultant-secondary`, `reviewer`) abstract CLI vendor selection away from skill logic; `planning-router` is an advisory Haiku helper used only when deterministic route signals conflict.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.human.diff:68:+- `providers-registry` — Skills refer to stable agent roles (`consultant-primary`, `consultant-secondary`, `reviewer`) while provider resolution happens behind those roles.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/agents.llm.json:9:    "agents/consultant-primary.md",
./z-harness/archive/docs/20260525T081955Z-docs/proposed/agents.llm.json:26:    {"file": "agents/consultant-primary.md", "line": 1, "symbol": "consultant-primary", "kind": "module", "summary": "Primary provider proxy for consult/review modes."},
./z-harness/archive/docs/20260525T081955Z-docs/proposed/agents.llm.json:43:    "consultant-primary, consultant-secondary, and reviewer resolve providers via scripts/resolve-provider.sh.",
./z-harness/archive/docs/20260525T081955Z-docs/proposed/skills.llm.json:52:    "Consults use consultant-primary/secondary; review uses reviewer.",
./z-harness/archive/docs/20260525T081955Z-docs/proposed/agents.human.md:4:> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/planning-router.md, agents/remote-runner.md, agents/reviewer.md, agents/spec-precheck.md
./z-harness/archive/docs/20260525T081955Z-docs/proposed/agents.human.md:10:The suite is split by responsibility: planning route advice (`planning-router`), cluster planning (`cluster-planner`), complexity stamping (`complexity-classifier`), implementation (`implementer`), correctness review (`reviewer`), code-quality review (`mr-reviewer`), spec validation (`spec-precheck`), documentation (`doc-fetcher`, `doc-updater`), external lookup (`external-lookup`), remote verification (`remote-runner`), auditing (`auditor`), and cross-LLM consultation (`consultant-primary`, `consultant-secondary`). The consultant and reviewer proxy agents resolve provider CLIs at runtime through `scripts/resolve-provider.sh`; the concrete provider is not hard-coded in the agent prompt.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/agents.human.md:17:- `agents/consultant-primary.md:1` — `consultant-primary` — Provider-agnostic primary consultant proxy; supports planning, review, debug, brainstorm, research, docs, test, and MR-review modes.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/agents.human.md:38:- `consultant-primary`, `consultant-secondary`, and `reviewer` are Haiku proxy prompts that shell out to provider CLIs resolved at runtime. Old hard-coded `codex-consultant.md`, `gemini-consultant.md`, and `codex-reviewer.md` references are stale.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/skills.human.md:10:The current skill family has converged on a shared route-policy model. Planning and execution skills collect deterministic signals, call the advisory `planning-router` only when those signals conflict, write `route-decision.md`, emit `plan_route_decision`, preserve command-specific telemetry, present an AskUser handoff, and stop rather than auto-running the recommended target. The skills also assume the provider-registry agent names (`consultant-primary`, `consultant-secondary`, `reviewer`), shared scripts for path resolution and logging, and docs/memory maintenance through `doc-updater`, `/z-maintain-docs`, and `/z-suggest-memory`.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/skills.human.md:39:- `providers-registry` — Skills refer to stable agent roles (`consultant-primary`, `consultant-secondary`, `reviewer`) while provider resolution happens behind those roles.
./z-harness/archive/docs/20260524T235238Z-docs/proposed/agents.llm.json:9:    "agents/consultant-primary.md",
./z-harness/archive/docs/20260524T235238Z-docs/proposed/agents.llm.json:25:    {"file": "agents/consultant-primary.md", "line": 1, "symbol": "consultant-primary", "kind": "module", "summary": "Haiku proxy; resolves primary consultant provider via resolve-provider.sh; 11 modes; emits consult_start for liveness; uses check-timeout.sh."},
./z-harness/archive/docs/20260524T235238Z-docs/proposed/agents.llm.json:26:    {"file": "agents/consultant-secondary.md", "line": 1, "symbol": "consultant-secondary", "kind": "module", "summary": "Haiku proxy; resolves secondary consultant provider (must differ from primary); same 11 modes as consultant-primary."},
./z-harness/archive/docs/20260524T235238Z-docs/proposed/agents.llm.json:40:    "consultant-primary, consultant-secondary, and reviewer resolve their provider at runtime via scripts/resolve-provider.sh - they are not hard-coded to any specific LLM.",
./z-harness/archive/docs/20260524T235238Z-docs/proposed/agents.llm.json:43:    "consultant-primary, consultant-secondary, and reviewer emit consult_start / review_start BEFORE the provider call so liveness.sh can detect hangs."
./z-harness/archive/docs/20260524T235238Z-docs/proposed/agents.llm.json:46:    "codex-consultant.md, codex-reviewer.md, and gemini-consultant.md no longer exist - replaced by consultant-primary.md, consultant-secondary.md, reviewer.md with runtime provider resolution.",
./z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.llm.json:27:    {"file": "skills/z-brainstorm/SKILL.md", "line": 1, "symbol": "z-brainstorm", "kind": "module", "summary": "Three-vendor parallel ideation (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check; produces BRAINSTORM.md."},
./z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.llm.json:48:    "Cross-LLM consult agents are always referenced as consultant-primary and consultant-secondary; code review uses the reviewer agent.",
./z-harness/archive/docs/20260524T235238Z-docs/proposed/agents.human.md:4:> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/remote-runner.md, agents/reviewer.md, agents/spec-precheck.md
./z-harness/archive/docs/20260524T235238Z-docs/proposed/agents.human.md:10:These agents decompose complex workflows into focused roles: planning (cluster-planner), implementation (implementer), correctness review (reviewer), code quality review (mr-reviewer), spec validation (spec-precheck), complexity routing (complexity-classifier), documentation (doc-fetcher, doc-updater), remote execution (remote-runner), external retrieval (external-lookup), auditing (auditor), and cross-LLM consultation (consultant-primary, consultant-secondary). The consultant and reviewer agents are provider-agnostic proxies: they call `scripts/resolve-provider.sh` to discover which CLI (Codex, Gemini, or another) is registered for each role, then shell out to that CLI. This replaced the earlier hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files.
./z-harness/archive/docs/20260524T235238Z-docs/proposed/agents.human.md:17:- `agents/consultant-primary.md:1` — `consultant-primary` — Provider-agnostic proxy for the primary consultant LLM (resolved via `scripts/resolve-provider.sh consultant_primary`). Supports 11 modes: `bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `brainstorm`, `research-review`, `doc-audit`, `test-cases`, `mr-review`, `generate-hypotheses-round1`, `generate-hypotheses-round2-adversarial`. Emits `consult_start` before the provider call for liveness detection; uses `scripts/check-timeout.sh` to detect and wrap calls with `timeout(1)` / `gtimeout` when available.
./z-harness/archive/docs/20260524T235238Z-docs/proposed/agents.human.md:18:- `agents/consultant-secondary.md:1` — `consultant-secondary` — Identical shape to consultant-primary but resolves `consultant_secondary` — must be a distinct provider. Same 11 modes.
./z-harness/archive/docs/20260524T235238Z-docs/proposed/agents.human.md:23:- `agents/mr-reviewer.md:1` — `mr-reviewer` — Multi-LLM code-quality reviewer (not correctness); targets AI-shaped slop, defensive bloat, test noise, abstraction failures, style drift. Fans out to `consultant-primary` / `consultant-secondary` voices in parallel, deduplicates findings by `(file, category, normalized_text)`, applies consensus tier-bumps and dismissal-pattern Jaccard matching. Returns fenced JSON + `## Summary` block.
./z-harness/archive/docs/20260524T235238Z-docs/proposed/agents.human.md:37:- `consultant-primary`, `consultant-secondary`, and `reviewer` are provider-agnostic proxy shells (Haiku model) that shell out to an external CLI; the actual reasoning model is whatever `resolve-provider.sh` returns. The old hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files no longer exist — references to them in archived transcripts or old docs are stale.
./z-harness/archive/docs/20260524T235238Z-docs/proposed/agents.human.md:38:- All three proxy agents (`consultant-primary`, `consultant-secondary`, `reviewer`) now source `scripts/check-timeout.sh` before calling the provider CLI. This sets `$TIMEOUT_CMD` and emits a `timeout_availability` event once per run so silent timeouts are debuggable. They also emit a `consult_start` / `review_start` event BEFORE the provider call so `scripts/liveness.sh` can detect hung consultants even when `$TIMEOUT_CMD` is empty.
./z-harness/archive/docs/20260524T235238Z-docs/proposed/agents.human.md:47:- `/z-plan` Phase 3 dispatches `consultant-primary` and `consultant-secondary` in parallel with `MODE: bundled-decisions`; each resolves its provider CLI via `scripts/resolve-provider.sh` and returns a standard wrapper response.
./z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.human.md:10:All skills share a common set of infrastructure assumptions established in the 2026-05-24 portable-harness migration: plan artifacts are resolved via `scripts/plan-path.sh` to `$Z_HARNESS_PLAN_DIR` (rather than hardcoded `z-harness/<slug>/` paths), cross-LLM consults use the provider-registry agents `consultant-primary` and `consultant-secondary`, and code review uses the `reviewer` agent. These agent names are stable identifiers that map to actual CLI vendors through the provider registry — skills never reference `gemini-consultant`, `codex-consultant`, or `codex-reviewer` directly.
./z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.human.md:15:- `skills/z-brainstorm/SKILL.md:1` — `z-brainstorm` — Parallel pre-plan ideation: three vendor-diverse ideators (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check, producing BRAINSTORM.md with `chosen_framing`.
./z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.human.md:35:- `agents` — Skills define the exact subagent types, models, and prompt shapes dispatched during runs. The provider-registry agents (`consultant-primary`, `consultant-secondary`, `reviewer`) abstract CLI vendor selection away from skill logic.
./z-harness/archive/20260525T205931Z-memory-self-improvement-loop/events.jsonl:2:{"ts":"2026-05-25T21:06:07Z","run":"20260525T205931Z-memory-self-improvement-loop","kind":"consult","role":"consultant_primary","provider":"gemini","model_label":"gemini-2.5-pro","mode":"brainstorm","prompt_chars":1789,"response_chars":3614,"wall_ms":34000,"transcript":"001-consultant-primary-gemini-brainstorm"}
./z-harness/archive/tasks/T006/review.prompt.md:362:1024|-diff --git a/exports/agy/prompts/consultant-primary.md b/exports/agy/prompts/consultant-primary.md
./z-harness/archive/tasks/T006/review.prompt.md:364:1026|---- a/exports/agy/prompts/consultant-primary.md
./z-harness/archive/tasks/T006/review.prompt.md:365:1027|-+++ b/exports/agy/prompts/consultant-primary.md
./z-harness/archive/tasks/T006/review.prompt.md:654:4954|+diff --git a/exports/agy/prompts/consultant-primary.md b/exports/agy/prompts/consultant-primary.md
./z-harness/archive/tasks/T006/review.prompt.md:656:4956|+--- a/exports/agy/prompts/consultant-primary.md
./z-harness/archive/tasks/T006/review.prompt.md:657:4957|++++ b/exports/agy/prompts/consultant-primary.md
./z-harness/archive/tasks/T006/review.prompt.md:1618:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T006/review.prompt.md:1821:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T006/review.prompt.md:2332:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T006/review.prompt.md:2548:  - id: consultant-primary
./z-harness/archive/tasks/T006/review.prompt.md:2549:    source: agents/consultant-primary.md
./z-harness/archive/tasks/T006/review.prompt.md:2550:    output: .agent/rules/z-harness-consultant-primary.md
./z-harness/archive/tasks/T006/review.prompt.md:2557:    description: "Routes to the secondary consultant LLM (resolved via providers registry) for a second opinion on an engineering decision or to review a plan. Use during /z-plan as the cross-LLM counterpart to consultant-primary — must resolve to a distinct provider."
./z-harness/archive/tasks/T006/review.response.md:377:1024|-diff --git a/exports/agy/prompts/consultant-primary.md b/exports/agy/prompts/consultant-primary.md
./z-harness/archive/tasks/T006/review.response.md:379:1026|---- a/exports/agy/prompts/consultant-primary.md
./z-harness/archive/tasks/T006/review.response.md:380:1027|-+++ b/exports/agy/prompts/consultant-primary.md
./z-harness/archive/tasks/T006/review.response.md:669:4954|+diff --git a/exports/agy/prompts/consultant-primary.md b/exports/agy/prompts/consultant-primary.md
./z-harness/archive/tasks/T006/review.response.md:671:4956|+--- a/exports/agy/prompts/consultant-primary.md
./z-harness/archive/tasks/T006/review.response.md:672:4957|++++ b/exports/agy/prompts/consultant-primary.md
./z-harness/archive/tasks/T006/review.response.md:1633:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T006/review.response.md:1836:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T006/review.response.md:2347:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T006/review.response.md:2563:  - id: consultant-primary
./z-harness/archive/tasks/T006/review.response.md:2564:    source: agents/consultant-primary.md
./z-harness/archive/tasks/T006/review.response.md:2565:    output: .agent/rules/z-harness-consultant-primary.md
./z-harness/archive/tasks/T006/review.response.md:2572:    description: "Routes to the secondary consultant LLM (resolved via providers registry) for a second opinion on an engineering decision or to review a plan. Use during /z-plan as the cross-LLM counterpart to consultant-primary — must resolve to a distinct provider."
./z-harness/archive/tasks/T006/review.response.md:3024:agents/consultant-primary.md
./z-harness/archive/tasks/T006/review.response.md:3039:exports/agy/.agent/rules/z-harness-consultant-primary.md
./z-harness/archive/tasks/T006/review.response.md:3063:exports/agy/prompts/consultant-primary.md
./z-harness/archive/tasks/T006/review.response.md:3098:exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/archive/tasks/T006/review.response.md:3129:M	agents/consultant-primary.md
./z-harness/archive/tasks/T006/review.response.md:3155:M	exports/agy/.agent/rules/z-harness-consultant-primary.md
./z-harness/archive/tasks/T006/review.response.md:3179:M	exports/agy/prompts/consultant-primary.md
./z-harness/archive/tasks/T006/review.response.md:3214:M	exports/cursor/.cursor/rules/consultant-primary.mdc
./z-harness/archive/tasks/T006/review.response.md:3258:.agent/rules/z-harness-consultant-primary.md
./z-harness/archive/tasks/T001/review.prompt.md:421:-> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/archive/tasks/T001/review.prompt.md:423:+> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/planning-router.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/archive/tasks/T001/review.prompt.md:438: - `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
./z-harness/archive/tasks/T001/review.prompt.md:890:> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/planning-router.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/archive/tasks/T001/review.prompt.md:907:- `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
./z-harness/archive/tasks/T001/review.response.md:436:-> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/archive/tasks/T001/review.response.md:438:+> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/planning-router.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/archive/tasks/T001/review.response.md:453: - `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
./z-harness/archive/tasks/T001/review.response.md:905:> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/planning-router.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/archive/tasks/T001/review.response.md:922:- `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
./z-harness/archive/tasks/T001/review.response.md:975:-> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/archive/tasks/T001/review.response.md:977:+> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/planning-router.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/archive/tasks/T001/review.response.md:992: - `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
./z-harness/archive/tasks/T001/review.response.md:1130:/bin/zsh -lc 'rg -n "planning-router|plan_route_decision|PLAN_ROUTE_CHECK|z-audit-plan|external-lookup|gemini-consultant|consultant-primary|mr-reviewer" agents docs commands skills scripts -S' in /Users/zeke/dev/z-harness
./z-harness/archive/tasks/T001/review.response.md:1132:docs/human/agents.md:4:> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/planning-router.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/archive/tasks/T001/review.response.md:1134:docs/human/agents.md:21:- `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
./z-harness/archive/tasks/T001/review.response.md:1137:docs/human/style-init.md:40:After the draft is generated from the Capture files and interview answers, the configured `consultant-primary` and `consultant-secondary` providers critique it in parallel (flagging missing categories, vague rules, contradictions). The critique is applied, and you are asked to approve, edit, re-critique, or abandon.
./z-harness/archive/tasks/T001/review.response.md:1142:commands/z-audit-plan.md:98:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1143:commands/z-improve.md:117:Agent(subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1144:docs/human/INDEX.md:13:| [agents](./agents.md) | high | `agents/auditor.md`, `agents/cluster-planner.md`, `agents/consultant-primary.md` | Scrutinizes codebase targets across correctness/perf/cleanliness/design. |
./z-harness/archive/tasks/T001/review.response.md:1145:skills/z-review-all/SKILL.md:121:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1146:agents/consultant-primary.md:2:name: consultant-primary
./z-harness/archive/tasks/T001/review.response.md:1147:agents/consultant-primary.md:8:<!-- auto-generated shape: consultant-primary | consultant-secondary | reviewer differ only in ROLE below -->
./z-harness/archive/tasks/T001/review.response.md:1148:agents/consultant-primary.md:78:- **`mr-review`** (Step 4 of `mr-reviewer`): caller hands you active categories, full STYLE.md contents, and the full diff. Ask the provider to find quality issues (not correctness bugs) in the diff, citing STYLE.md rule IDs for style-drift findings and file:line for abstraction findings. Return RAW — the caller expects a fenced `json` block with `{"findings": [...]}` matching the schema in the prompt; do not apply the standard wrapper.
./z-harness/archive/tasks/T001/review.response.md:1149:agents/consultant-primary.md:142:SLUG="consultant-primary-${PROVIDER}-$MODE"
./z-harness/archive/tasks/T001/review.response.md:1150:commands/z-review-all.md:130:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1151:commands/z-plan-light.md:80:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1153:docs/human/mr-reviewer.md:10:The review fans out to all available LLM voices (Claude Sonnet inline, plus the configured `consultant-primary` and `consultant-secondary` providers). Findings are deduplicated, tagged by which voices raised them, ranked P0–P4, and written to `z-harness/<slug>/MR-REVIEW.md` in `TASKS.md`-compatible shape. The command **never blocks** — you triage by deleting unwanted findings from MR-REVIEW.md, then run `/z-implement-all --tasks=z-harness/<slug>/MR-REVIEW.md` on survivors.
./z-harness/archive/tasks/T001/review.response.md:1162:commands/z-style-init.md:259:Dispatch `consultant-secondary` and `consultant-primary` **in parallel in a single message** with `MODE: style-critique`:
./z-harness/archive/tasks/T001/review.response.md:1163:commands/z-style-init.md:280:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1164:commands/z-plan.md:208:- `Agent(subagent_type="consultant-primary", ...)`
./z-harness/archive/tasks/T001/review.response.md:1165:commands/z-plan.md:260:- consultant-primary: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/archive/tasks/T001/review.response.md:1169:commands/z-amend.md:122:Agent(subagent_type="consultant-primary", description="Amend consult (Gemini) for <slug>",
./z-harness/archive/tasks/T001/review.response.md:1170:skills/z-research/SKILL.md:222:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1180:skills/z-audit-plan/SKILL.md:98:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1181:commands/z-maintain-docs.md:85:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1191:agents/consultant-secondary.md:3:description: Routes to the secondary consultant LLM (resolved via providers registry) for a second opinion on an engineering decision or to review a plan. Use during /z-plan as the cross-LLM counterpart to consultant-primary — must resolve to a distinct provider.
./z-harness/archive/tasks/T001/review.response.md:1192:agents/consultant-secondary.md:8:<!-- auto-generated shape: consultant-primary | consultant-secondary | reviewer differ only in ROLE below -->
./z-harness/archive/tasks/T001/review.response.md:1194:commands/z-test.md:110:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1195:commands/z-test.md:227:- **No new agents dispatched.** Reuses `consultant-primary` and `consultant-secondary` only.
./z-harness/archive/tasks/T001/review.response.md:1202:agents/reviewer.md:8:<!-- auto-generated shape: consultant-primary | consultant-secondary | reviewer differ only in ROLE below -->
./z-harness/archive/tasks/T001/review.response.md:1204:agents/mr-reviewer.md:191:**Consultant prompt shape (same for both consultant-secondary and consultant-primary):**
./z-harness/archive/tasks/T001/review.response.md:1205:agents/mr-reviewer.md:195:  subagent_type="consultant-secondary",   # or "consultant-primary"
./z-harness/archive/tasks/T001/review.response.md:1206:commands/z-audit.md:138:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1207:commands/z-brainstorm.md:149:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1208:commands/z-fix.md:104:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1221:skills/z-debug/SKILL.md:160:     subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1222:skills/z-debug/SKILL.md:195:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1223:skills/z-debug/SKILL.md:362:   Agent(subagent_type="consultant-primary", description="Fix consult for <slug>",
./z-harness/archive/tasks/T001/review.response.md:1224:commands/z-debug.md:167:     subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1225:commands/z-debug.md:202:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1226:commands/z-debug.md:369:   Agent(subagent_type="consultant-primary", description="Fix consult for <slug>",
./z-harness/archive/tasks/T001/review.response.md:1227:skills/z-test/SKILL.md:110:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1228:skills/z-test/SKILL.md:227:- **No new agents dispatched.** Reuses `consultant-primary` and `consultant-secondary` only.
./z-harness/archive/tasks/T001/review.response.md:1229:skills/z-maintain-docs/SKILL.md:85:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1233:skills/z-improve/SKILL.md:118:Agent(subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1234:skills/z-plan-light/SKILL.md:81:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1236:skills/z-brainstorm/SKILL.md:150:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1242:commands/z-research.md:221:  subagent_type="consultant-primary",
./z-harness/archive/tasks/T001/review.response.md:1243:skills/z-amend/SKILL.md:125:Agent(subagent_type="consultant-primary", description="Amend consult (Gemini) for <slug>",
./z-harness/archive/tasks/T001/review.response.md:1244:skills/z-plan/SKILL.md:201:- `Agent(subagent_type="consultant-primary", ...)`
./z-harness/archive/tasks/T001/review.response.md:1245:skills/z-plan/SKILL.md:253:- consultant-primary: "Critique this plan. What's wrong, missing, or fragile?"
./z-harness/archive/tasks/T001/review.response.md:1251: M agents/consultant-primary.md
./z-harness/archive/tasks/subagent-liveness/v4-findings.md:9:2. **Location:** scripts/liveness.sh:114 plus agents/consultant-primary.md:41 / agents/consultant-secondary.md:41
./z-harness/archive/tasks/subagent-liveness/review.prompt.md:19:diff --git a/agents/consultant-primary.md b/agents/consultant-primary.md
./z-harness/archive/tasks/subagent-liveness/review.prompt.md:21:--- a/agents/consultant-primary.md
./z-harness/archive/tasks/subagent-liveness/review.prompt.md:22:+++ b/agents/consultant-primary.md
./z-harness/archive/tasks/subagent-liveness/review.response.md:2:- **Blocker** `agents/consultant-primary.md:28`, `agents/consultant-secondary.md:28`, `agents/reviewer.md:28`: the new pre-call path sets `RUN` to a literal placeholder and has no fallback to derive the run id before sourcing `check-timeout.sh` or emitting `consult_start`, so a caller that omits the run id logs liveness events under the wrong archive path before the existing Archiving fallback can run. Move the run-id derivation before `check-timeout.sh` and reuse that same resolved `RUN` for pre-call events, transcripts, and post-call events.
./z-harness/archive/tasks/subagent-liveness/review.response.md:4:- **Major** `agents/consultant-primary.md:42`, `agents/consultant-secondary.md:42`: the `consult_start` JSON is built with `printf` string interpolation, so a provider or mode containing JSON-special characters produces invalid JSON and gets wrapped as `{"raw": ...}` by `log-event.sh`; then `role` is no longer a top-level field and the liveness close logic regresses. Build this payload with `python3 -c 'json.dumps(...)'` the same way `check-timeout.sh` does.
./z-harness/archive/tasks/subagent-liveness/review.response.md:11:- **Blocker** `agents/consultant-primary.md:28`, `agents/consultant-secondary.md:28`, `agents/reviewer.md:28`: the new pre-call path sets `RUN` to a literal placeholder and has no fallback to derive the run id before sourcing `check-timeout.sh` or emitting `consult_start`, so a caller that omits the run id logs liveness events under the wrong archive path before the existing Archiving fallback can run. Move the run-id derivation before `check-timeout.sh` and reuse that same resolved `RUN` for pre-call events, transcripts, and post-call events.
./z-harness/archive/tasks/subagent-liveness/review.response.md:13:- **Major** `agents/consultant-primary.md:42`, `agents/consultant-secondary.md:42`: the `consult_start` JSON is built with `printf` string interpolation, so a provider or mode containing JSON-special characters produces invalid JSON and gets wrapped as `{"raw": ...}` by `log-event.sh`; then `role` is no longer a top-level field and the liveness close logic regresses. Build this payload with `python3 -c 'json.dumps(...)'` the same way `check-timeout.sh` does.
./z-harness/archive/tasks/subagent-liveness/review.findings.md:5:1. **RUN placeholder not derived before sourcing check-timeout.sh** (`agents/consultant-primary.md:28`, `agents/consultant-secondary.md:28`, `agents/reviewer.md:28`): The pre-call path sets `RUN` to a literal `"<run-id from caller>"` placeholder string with no fallback to derive the actual run id before sourcing `check-timeout.sh` or emitting `consult_start`. This logs liveness events to the wrong archive path. Derive the run id at the top of the agent file (reuse existing Archiving section logic) and thread it through all event calls.
./z-harness/archive/tasks/subagent-liveness/review.findings.md:7:2. **consult_start JSON not escaped** (`agents/consultant-primary.md:42`, `agents/consultant-secondary.md:42`): The `printf` string interpolation for `role`/`mode`/`provider` will produce invalid JSON if provider or mode contain JSON-special characters (quotes, backslashes, newlines), causing `log-event.sh` to wrap it as `{"raw": ...}` and lose the top-level `role` field that liveness matching depends on. Build the JSON payload with `python3 -c 'json.dumps(...)'` the same way `check-timeout.sh` does.
./z-harness/archive/tasks/T004/review.response.md:83:z-harness/archive/tasks/subagent-liveness/review.response.md:4:- **Major** `agents/consultant-primary.md:42`, `agents/consultant-secondary.md:42`: the `consult_start` JSON is built with `printf` string interpolation, so a provider or mode containing JSON-special characters produces invalid JSON and gets wrapped as `{"raw": ...}` by `log-event.sh`; then `role` is no longer a top-level field and the liveness close logic regresses. Build this payload with `python3 -c 'json.dumps(...)'` the same way `check-timeout.sh` does.
./z-harness/archive/tasks/T004/review.response.md:85:z-harness/archive/tasks/subagent-liveness/review.response.md:13:- **Major** `agents/consultant-primary.md:42`, `agents/consultant-secondary.md:42`: the `consult_start` JSON is built with `printf` string interpolation, so a provider or mode containing JSON-special characters produces invalid JSON and gets wrapped as `{"raw": ...}` by `log-event.sh`; then `role` is no longer a top-level field and the liveness close logic regresses. Build this payload with `python3 -c 'json.dumps(...)'` the same way `check-timeout.sh` does.
./z-harness/archive/tasks/T004/review.response.md:87:z-harness/archive/tasks/subagent-liveness/review.findings.md:7:2. **consult_start JSON not escaped** (`agents/consultant-primary.md:42`, `agents/consultant-secondary.md:42`): The `printf` string interpolation for `role`/`mode`/`provider` will produce invalid JSON if provider or mode contain JSON-special characters (quotes, backslashes, newlines), causing `log-event.sh` to wrap it as `{"raw": ...}` and lose the top-level `role` field that liveness matching depends on. Build the JSON payload with `python3 -c 'json.dumps(...)'` the same way `check-timeout.sh` does.
./z-harness/archive/tasks/T005/review.prompt.md:424:        "agents/consultant-primary.md",
./z-harness/archive/tasks/T005/review.prompt.md:910:    {"file": "skills/z-brainstorm/SKILL.md", "line": 1, "symbol": "z-brainstorm", "kind": "module", "summary": "Three-vendor parallel ideation (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check; produces BRAINSTORM.md."},
./z-harness/archive/tasks/T005/review.prompt.md:931:    "Cross-LLM consult agents are always referenced as consultant-primary and consultant-secondary; code review uses the reviewer agent.",
./z-harness/archive/tasks/T005/review.prompt.md:960:    "agents/consultant-primary.md",
./z-harness/archive/tasks/T005/review.prompt.md:977:    {"file": "agents/consultant-primary.md", "line": 1, "symbol": "consultant-primary", "kind": "module", "summary": "Haiku proxy; resolves primary consultant provider via resolve-provider.sh; 11 modes; emits consult_start for liveness; uses check-timeout.sh."},
./z-harness/archive/tasks/T005/review.prompt.md:978:    {"file": "agents/consultant-secondary.md", "line": 1, "symbol": "consultant-secondary", "kind": "module", "summary": "Haiku proxy; resolves secondary consultant provider (must differ from primary); same 11 modes as consultant-primary."},
./z-harness/archive/tasks/T005/review.prompt.md:993:    "consultant-primary, consultant-secondary, and reviewer resolve their provider at runtime via scripts/resolve-provider.sh - they are not hard-coded to any specific LLM.",
./z-harness/archive/tasks/T005/review.prompt.md:996:    "consultant-primary, consultant-secondary, and reviewer emit consult_start / review_start BEFORE the provider call so liveness.sh can detect hangs.",
./z-harness/archive/tasks/T005/review.prompt.md:1000:    "codex-consultant.md, codex-reviewer.md, and gemini-consultant.md no longer exist - replaced by consultant-primary.md, consultant-secondary.md, reviewer.md with runtime provider resolution.",
./z-harness/archive/tasks/T005/review.prompt.md:1021:-> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/archive/tasks/T005/review.prompt.md:1023:+> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/planning-router.md, agents/remote-runner.md, agents/reviewer.md, agents/spec-precheck.md
./z-harness/archive/tasks/T005/review.prompt.md:1031:+These agents decompose complex workflows into focused roles: planning (cluster-planner), planning-route disambiguation (planning-router), implementation (implementer), correctness review (reviewer), code quality review (mr-reviewer), spec validation (spec-precheck), complexity routing (complexity-classifier), documentation (doc-fetcher, doc-updater), remote execution (remote-runner), external retrieval (external-lookup), auditing (auditor), and cross-LLM consultation (consultant-primary, consultant-secondary). The consultant and reviewer agents are provider-agnostic proxies: they call `scripts/resolve-provider.sh` to discover which CLI (Codex, Gemini, or another) is registered for each role, then shell out to that CLI. This replaced the earlier hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files.
./z-harness/archive/tasks/T005/review.prompt.md:1041:-- `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
./z-harness/archive/tasks/T005/review.prompt.md:1049:+- `agents/consultant-primary.md:1` — `consultant-primary` — Provider-agnostic proxy for the primary consultant LLM (resolved via `scripts/resolve-provider.sh consultant_primary`). Supports 11 modes: `bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `brainstorm`, `research-review`, `doc-audit`, `test-cases`, `mr-review`, `generate-hypotheses-round1`, `generate-hypotheses-round2-adversarial`. Emits `consult_start` before the provider call for liveness detection; uses `scripts/check-timeout.sh` to detect and wrap calls with `timeout(1)` / `gtimeout` when available.
./z-harness/archive/tasks/T005/review.prompt.md:1050:+- `agents/consultant-secondary.md:1` — `consultant-secondary` — Identical shape to consultant-primary but resolves `consultant_secondary` — must be a distinct provider. Same 11 modes.
./z-harness/archive/tasks/T005/review.prompt.md:1055:+- `agents/mr-reviewer.md:1` — `mr-reviewer` — Multi-LLM code-quality reviewer (not correctness); targets AI-shaped slop, defensive bloat, test noise, abstraction failures, style drift. Fans out to `consultant-primary` / `consultant-secondary` voices in parallel, deduplicates findings by `(file, category, normalized_text)`, applies consensus tier-bumps and dismissal-pattern Jaccard matching. Returns fenced JSON + `## Summary` block.
./z-harness/archive/tasks/T005/review.prompt.md:1074:+- `consultant-primary`, `consultant-secondary`, and `reviewer` are provider-agnostic proxy shells (Haiku model) that shell out to an external CLI; the actual reasoning model is whatever `resolve-provider.sh` returns. The old hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files no longer exist — references to them in archived transcripts or old docs are stale.
./z-harness/archive/tasks/T005/review.prompt.md:1075:+- All three proxy agents (`consultant-primary`, `consultant-secondary`, `reviewer`) now source `scripts/check-timeout.sh` before calling the provider CLI. This sets `$TIMEOUT_CMD` and emits a `timeout_availability` event once per run so silent timeouts are debuggable. They also emit a `consult_start` / `review_start` event BEFORE the provider call so `scripts/liveness.sh` can detect hung consultants even when `$TIMEOUT_CMD` is empty.
./z-harness/archive/tasks/T005/review.prompt.md:1087:+- `/z-plan` Phase 3 dispatches `consultant-primary` and `consultant-secondary` in parallel with `MODE: bundled-decisions`; each resolves its provider CLI via `scripts/resolve-provider.sh` and returns a standard wrapper response.
./z-harness/archive/tasks/T005/review.prompt.md:1159:+All skills share a common set of infrastructure assumptions established in the 2026-05-24 portable-harness migration: plan artifacts are resolved via `scripts/plan-path.sh` to `$Z_HARNESS_PLAN_DIR` (rather than hardcoded `z-harness/<slug>/` paths), cross-LLM consults use the provider-registry agents `consultant-primary` and `consultant-secondary`, and code review uses the `reviewer` agent. These agent names are stable identifiers that map to actual CLI vendors through the provider registry — skills never reference `gemini-consultant`, `codex-consultant`, or `codex-reviewer` directly.
./z-harness/archive/tasks/T005/review.prompt.md:1182:+- `skills/z-brainstorm/SKILL.md:1` — `z-brainstorm` — Parallel pre-plan ideation: three vendor-diverse ideators (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check, producing BRAINSTORM.md with `chosen_framing`.
./z-harness/archive/tasks/T005/review.prompt.md:1205:+- `agents` — Skills define the exact subagent types, models, and prompt shapes dispatched during runs. The provider-registry agents (`consultant-primary`, `consultant-secondary`, `reviewer`) abstract CLI vendor selection away from skill logic; `planning-router` is an advisory Haiku helper used only when deterministic route signals conflict.
./z-harness/archive/tasks/T005/review.prompt.md:1242:+        "agents/consultant-primary.md",
./z-harness/archive/tasks/T005/review.prompt.md:1373:+    "agents/consultant-primary.md",
./z-harness/archive/tasks/T005/review.prompt.md:1508:+    {"file": "agents/consultant-primary.md", "line": 1, "symbol": "consultant-primary", "kind": "module", "summary": "Haiku proxy; resolves primary consultant provider via resolve-provider.sh; 11 modes; emits consult_start for liveness; uses check-timeout.sh."},
./z-harness/archive/tasks/T005/review.prompt.md:1509:+    {"file": "agents/consultant-secondary.md", "line": 1, "symbol": "consultant-secondary", "kind": "module", "summary": "Haiku proxy; resolves secondary consultant provider (must differ from primary); same 11 modes as consultant-primary."},
./z-harness/archive/tasks/T005/review.prompt.md:1526:+    "consultant-primary, consultant-secondary, and reviewer resolve their provider at runtime via scripts/resolve-provider.sh - they are not hard-coded to any specific LLM.",
./z-harness/archive/tasks/T005/review.prompt.md:1529:+    "consultant-primary, consultant-secondary, and reviewer emit consult_start / review_start BEFORE the provider call so liveness.sh can detect hangs.",
./z-harness/archive/tasks/T005/review.prompt.md:1534:+    "codex-consultant.md, codex-reviewer.md, and gemini-consultant.md no longer exist - replaced by consultant-primary.md, consultant-secondary.md, reviewer.md with runtime provider resolution.",
./z-harness/archive/tasks/T005/review.prompt.md:1762:+    {"file": "skills/z-brainstorm/SKILL.md", "line": 1, "symbol": "z-brainstorm", "kind": "module", "summary": "Three-vendor parallel ideation (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check; produces BRAINSTORM.md."},
./z-harness/archive/tasks/T005/review.prompt.md:1785:+    "Cross-LLM consult agents are always referenced as consultant-primary and consultant-secondary; code review uses the reviewer agent.",
./z-harness/archive/tasks/T005/review.response.md:439:        "agents/consultant-primary.md",
./z-harness/archive/tasks/T005/review.response.md:925:    {"file": "skills/z-brainstorm/SKILL.md", "line": 1, "symbol": "z-brainstorm", "kind": "module", "summary": "Three-vendor parallel ideation (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check; produces BRAINSTORM.md."},
./z-harness/archive/tasks/T005/review.response.md:946:    "Cross-LLM consult agents are always referenced as consultant-primary and consultant-secondary; code review uses the reviewer agent.",
./z-harness/archive/tasks/T005/review.response.md:975:    "agents/consultant-primary.md",
./z-harness/archive/tasks/T005/review.response.md:992:    {"file": "agents/consultant-primary.md", "line": 1, "symbol": "consultant-primary", "kind": "module", "summary": "Haiku proxy; resolves primary consultant provider via resolve-provider.sh; 11 modes; emits consult_start for liveness; uses check-timeout.sh."},
./z-harness/archive/tasks/T005/review.response.md:993:    {"file": "agents/consultant-secondary.md", "line": 1, "symbol": "consultant-secondary", "kind": "module", "summary": "Haiku proxy; resolves secondary consultant provider (must differ from primary); same 11 modes as consultant-primary."},
./z-harness/archive/tasks/T005/review.response.md:1008:    "consultant-primary, consultant-secondary, and reviewer resolve their provider at runtime via scripts/resolve-provider.sh - they are not hard-coded to any specific LLM.",
./z-harness/archive/tasks/T005/review.response.md:1011:    "consultant-primary, consultant-secondary, and reviewer emit consult_start / review_start BEFORE the provider call so liveness.sh can detect hangs.",
./z-harness/archive/tasks/T005/review.response.md:1015:    "codex-consultant.md, codex-reviewer.md, and gemini-consultant.md no longer exist - replaced by consultant-primary.md, consultant-secondary.md, reviewer.md with runtime provider resolution.",
./z-harness/archive/tasks/T005/review.response.md:1036:-> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/archive/tasks/T005/review.response.md:1038:+> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/planning-router.md, agents/remote-runner.md, agents/reviewer.md, agents/spec-precheck.md
./z-harness/archive/tasks/T005/review.response.md:1046:+These agents decompose complex workflows into focused roles: planning (cluster-planner), planning-route disambiguation (planning-router), implementation (implementer), correctness review (reviewer), code quality review (mr-reviewer), spec validation (spec-precheck), complexity routing (complexity-classifier), documentation (doc-fetcher, doc-updater), remote execution (remote-runner), external retrieval (external-lookup), auditing (auditor), and cross-LLM consultation (consultant-primary, consultant-secondary). The consultant and reviewer agents are provider-agnostic proxies: they call `scripts/resolve-provider.sh` to discover which CLI (Codex, Gemini, or another) is registered for each role, then shell out to that CLI. This replaced the earlier hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files.
./z-harness/archive/tasks/T005/review.response.md:1056:-- `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
./z-harness/archive/tasks/T005/review.response.md:1064:+- `agents/consultant-primary.md:1` — `consultant-primary` — Provider-agnostic proxy for the primary consultant LLM (resolved via `scripts/resolve-provider.sh consultant_primary`). Supports 11 modes: `bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `brainstorm`, `research-review`, `doc-audit`, `test-cases`, `mr-review`, `generate-hypotheses-round1`, `generate-hypotheses-round2-adversarial`. Emits `consult_start` before the provider call for liveness detection; uses `scripts/check-timeout.sh` to detect and wrap calls with `timeout(1)` / `gtimeout` when available.
./z-harness/archive/tasks/T005/review.response.md:1065:+- `agents/consultant-secondary.md:1` — `consultant-secondary` — Identical shape to consultant-primary but resolves `consultant_secondary` — must be a distinct provider. Same 11 modes.
./z-harness/archive/tasks/T005/review.response.md:1070:+- `agents/mr-reviewer.md:1` — `mr-reviewer` — Multi-LLM code-quality reviewer (not correctness); targets AI-shaped slop, defensive bloat, test noise, abstraction failures, style drift. Fans out to `consultant-primary` / `consultant-secondary` voices in parallel, deduplicates findings by `(file, category, normalized_text)`, applies consensus tier-bumps and dismissal-pattern Jaccard matching. Returns fenced JSON + `## Summary` block.
./z-harness/archive/tasks/T005/review.response.md:1089:+- `consultant-primary`, `consultant-secondary`, and `reviewer` are provider-agnostic proxy shells (Haiku model) that shell out to an external CLI; the actual reasoning model is whatever `resolve-provider.sh` returns. The old hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files no longer exist — references to them in archived transcripts or old docs are stale.
./z-harness/archive/tasks/T005/review.response.md:1090:+- All three proxy agents (`consultant-primary`, `consultant-secondary`, `reviewer`) now source `scripts/check-timeout.sh` before calling the provider CLI. This sets `$TIMEOUT_CMD` and emits a `timeout_availability` event once per run so silent timeouts are debuggable. They also emit a `consult_start` / `review_start` event BEFORE the provider call so `scripts/liveness.sh` can detect hung consultants even when `$TIMEOUT_CMD` is empty.
./z-harness/archive/tasks/T005/review.response.md:1102:+- `/z-plan` Phase 3 dispatches `consultant-primary` and `consultant-secondary` in parallel with `MODE: bundled-decisions`; each resolves its provider CLI via `scripts/resolve-provider.sh` and returns a standard wrapper response.
./z-harness/archive/tasks/T005/review.response.md:1174:+All skills share a common set of infrastructure assumptions established in the 2026-05-24 portable-harness migration: plan artifacts are resolved via `scripts/plan-path.sh` to `$Z_HARNESS_PLAN_DIR` (rather than hardcoded `z-harness/<slug>/` paths), cross-LLM consults use the provider-registry agents `consultant-primary` and `consultant-secondary`, and code review uses the `reviewer` agent. These agent names are stable identifiers that map to actual CLI vendors through the provider registry — skills never reference `gemini-consultant`, `codex-consultant`, or `codex-reviewer` directly.
./z-harness/archive/tasks/T005/review.response.md:1197:+- `skills/z-brainstorm/SKILL.md:1` — `z-brainstorm` — Parallel pre-plan ideation: three vendor-diverse ideators (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check, producing BRAINSTORM.md with `chosen_framing`.
./z-harness/archive/tasks/T005/review.response.md:1220:+- `agents` — Skills define the exact subagent types, models, and prompt shapes dispatched during runs. The provider-registry agents (`consultant-primary`, `consultant-secondary`, `reviewer`) abstract CLI vendor selection away from skill logic; `planning-router` is an advisory Haiku helper used only when deterministic route signals conflict.
./z-harness/archive/tasks/T005/review.response.md:1257:+        "agents/consultant-primary.md",
./z-harness/archive/tasks/T005/review.response.md:1388:+    "agents/consultant-primary.md",
./z-harness/archive/tasks/T005/review.response.md:1523:+    {"file": "agents/consultant-primary.md", "line": 1, "symbol": "consultant-primary", "kind": "module", "summary": "Haiku proxy; resolves primary consultant provider via resolve-provider.sh; 11 modes; emits consult_start for liveness; uses check-timeout.sh."},
./z-harness/archive/tasks/T005/review.response.md:1524:+    {"file": "agents/consultant-secondary.md", "line": 1, "symbol": "consultant-secondary", "kind": "module", "summary": "Haiku proxy; resolves secondary consultant provider (must differ from primary); same 11 modes as consultant-primary."},
./z-harness/archive/tasks/T005/review.response.md:1541:+    "consultant-primary, consultant-secondary, and reviewer resolve their provider at runtime via scripts/resolve-provider.sh - they are not hard-coded to any specific LLM.",
./z-harness/archive/tasks/T005/review.response.md:1544:+    "consultant-primary, consultant-secondary, and reviewer emit consult_start / review_start BEFORE the provider call so liveness.sh can detect hangs.",
./z-harness/archive/tasks/T005/review.response.md:1549:+    "codex-consultant.md, codex-reviewer.md, and gemini-consultant.md no longer exist - replaced by consultant-primary.md, consultant-secondary.md, reviewer.md with runtime provider resolution.",
./z-harness/archive/tasks/T005/review.response.md:1777:+    {"file": "skills/z-brainstorm/SKILL.md", "line": 1, "symbol": "z-brainstorm", "kind": "module", "summary": "Three-vendor parallel ideation (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check; produces BRAINSTORM.md."},
./z-harness/archive/tasks/T005/review.response.md:1800:+    "Cross-LLM consult agents are always referenced as consultant-primary and consultant-secondary; code review uses the reviewer agent.",
./z-harness/archive/tasks/T005/review.response.md:1916:docs/human/agents.md:4:> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/planning-router.md, agents/remote-runner.md, agents/reviewer.md, agents/spec-precheck.md
./z-harness/archive/tasks/T005/review.response.md:1917:docs/human/agents.md:10:These agents decompose complex workflows into focused roles: planning (cluster-planner), planning-route disambiguation (planning-router), implementation (implementer), correctness review (reviewer), code quality review (mr-reviewer), spec validation (spec-precheck), complexity routing (complexity-classifier), documentation (doc-fetcher, doc-updater), remote execution (remote-runner), external retrieval (external-lookup), auditing (auditor), and cross-LLM consultation (consultant-primary, consultant-secondary). The consultant and reviewer agents are provider-agnostic proxies: they call `scripts/resolve-provider.sh` to discover which CLI (Codex, Gemini, or another) is registered for each role, then shell out to that CLI. This replaced the earlier hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files.
./z-harness/archive/tasks/T005/review.response.md:1963:docs/human/skills.md:36:- `agents` — Skills define the exact subagent types, models, and prompt shapes dispatched during runs. The provider-registry agents (`consultant-primary`, `consultant-secondary`, `reviewer`) abstract CLI vendor selection away from skill logic; `planning-router` is an advisory Haiku helper used only when deterministic route signals conflict.
./z-harness/archive/tasks/T005/review.response.md:1999:-> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/remote-runner.md, agents/spec-precheck.md
./z-harness/archive/tasks/T005/review.response.md:2001:+> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/planning-router.md, agents/remote-runner.md, agents/reviewer.md, agents/spec-precheck.md
./z-harness/archive/tasks/T005/review.response.md:2009:+These agents decompose complex workflows into focused roles: planning (cluster-planner), planning-route disambiguation (planning-router), implementation (implementer), correctness review (reviewer), code quality review (mr-reviewer), spec validation (spec-precheck), complexity routing (complexity-classifier), documentation (doc-fetcher, doc-updater), remote execution (remote-runner), external retrieval (external-lookup), auditing (auditor), and cross-LLM consultation (consultant-primary, consultant-secondary). The consultant and reviewer agents are provider-agnostic proxies: they call `scripts/resolve-provider.sh` to discover which CLI (Codex, Gemini, or another) is registered for each role, then shell out to that CLI. This replaced the earlier hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files.
./z-harness/archive/tasks/T005/review.response.md:2019:-- `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
./z-harness/archive/tasks/T005/review.response.md:2027:+- `agents/consultant-primary.md:1` — `consultant-primary` — Provider-agnostic proxy for the primary consultant LLM (resolved via `scripts/resolve-provider.sh consultant_primary`). Supports 11 modes: `bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `brainstorm`, `research-review`, `doc-audit`, `test-cases`, `mr-review`, `generate-hypotheses-round1`, `generate-hypotheses-round2-adversarial`. Emits `consult_start` before the provider call for liveness detection; uses `scripts/check-timeout.sh` to detect and wrap calls with `timeout(1)` / `gtimeout` when available.
./z-harness/archive/tasks/T005/review.response.md:2028:+- `agents/consultant-secondary.md:1` — `consultant-secondary` — Identical shape to consultant-primary but resolves `consultant_secondary` — must be a distinct provider. Same 11 modes.
./z-harness/archive/tasks/T005/review.response.md:2033:+- `agents/mr-reviewer.md:1` — `mr-reviewer` — Multi-LLM code-quality reviewer (not correctness); targets AI-shaped slop, defensive bloat, test noise, abstraction failures, style drift. Fans out to `consultant-primary` / `consultant-secondary` voices in parallel, deduplicates findings by `(file, category, normalized_text)`, applies consensus tier-bumps and dismissal-pattern Jaccard matching. Returns fenced JSON + `## Summary` block.
./z-harness/archive/tasks/T005/review.response.md:2052:+- `consultant-primary`, `consultant-secondary`, and `reviewer` are provider-agnostic proxy shells (Haiku model) that shell out to an external CLI; the actual reasoning model is whatever `resolve-provider.sh` returns. The old hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files no longer exist — references to them in archived transcripts or old docs are stale.
./z-harness/archive/tasks/T005/review.response.md:2053:+- All three proxy agents (`consultant-primary`, `consultant-secondary`, `reviewer`) now source `scripts/check-timeout.sh` before calling the provider CLI. This sets `$TIMEOUT_CMD` and emits a `timeout_availability` event once per run so silent timeouts are debuggable. They also emit a `consult_start` / `review_start` event BEFORE the provider call so `scripts/liveness.sh` can detect hung consultants even when `$TIMEOUT_CMD` is empty.
./z-harness/archive/tasks/T005/review.response.md:2065:+- `/z-plan` Phase 3 dispatches `consultant-primary` and `consultant-secondary` in parallel with `MODE: bundled-decisions`; each resolves its provider CLI via `scripts/resolve-provider.sh` and returns a standard wrapper response.
./z-harness/archive/tasks/T005/review.response.md:2137:+All skills share a common set of infrastructure assumptions established in the 2026-05-24 portable-harness migration: plan artifacts are resolved via `scripts/plan-path.sh` to `$Z_HARNESS_PLAN_DIR` (rather than hardcoded `z-harness/<slug>/` paths), cross-LLM consults use the provider-registry agents `consultant-primary` and `consultant-secondary`, and code review uses the `reviewer` agent. These agent names are stable identifiers that map to actual CLI vendors through the provider registry — skills never reference `gemini-consultant`, `codex-consultant`, or `codex-reviewer` directly.
./z-harness/archive/tasks/T005/review.response.md:2160:+- `skills/z-brainstorm/SKILL.md:1` — `z-brainstorm` — Parallel pre-plan ideation: three vendor-diverse ideators (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check, producing BRAINSTORM.md with `chosen_framing`.
./z-harness/archive/tasks/T005/review.response.md:2183:+- `agents` — Skills define the exact subagent types, models, and prompt shapes dispatched during runs. The provider-registry agents (`consultant-primary`, `consultant-secondary`, `reviewer`) abstract CLI vendor selection away from skill logic; `planning-router` is an advisory Haiku helper used only when deterministic route signals conflict.
./z-harness/archive/tasks/T005/review.response.md:2220:+        "agents/consultant-primary.md",
./z-harness/archive/tasks/T005/review.response.md:2351:+    "agents/consultant-primary.md",
./z-harness/archive/tasks/T005/review.response.md:2486:+    {"file": "agents/consultant-primary.md", "line": 1, "symbol": "consultant-primary", "kind": "module", "summary": "Haiku proxy; resolves primary consultant provider via resolve-provider.sh; 11 modes; emits consult_start for liveness; uses check-timeout.sh."},
./z-harness/archive/tasks/T005/review.response.md:2487:+    {"file": "agents/consultant-secondary.md", "line": 1, "symbol": "consultant-secondary", "kind": "module", "summary": "Haiku proxy; resolves secondary consultant provider (must differ from primary); same 11 modes as consultant-primary."},
./z-harness/archive/tasks/T005/review.response.md:2504:+    "consultant-primary, consultant-secondary, and reviewer resolve their provider at runtime via scripts/resolve-provider.sh - they are not hard-coded to any specific LLM.",
./z-harness/archive/tasks/T005/review.response.md:2507:+    "consultant-primary, consultant-secondary, and reviewer emit consult_start / review_start BEFORE the provider call so liveness.sh can detect hangs.",
./z-harness/archive/tasks/T005/review.response.md:2512:+    "codex-consultant.md, codex-reviewer.md, and gemini-consultant.md no longer exist - replaced by consultant-primary.md, consultant-secondary.md, reviewer.md with runtime provider resolution.",
./z-harness/archive/tasks/T005/review.response.md:2740:+    {"file": "skills/z-brainstorm/SKILL.md", "line": 1, "symbol": "z-brainstorm", "kind": "module", "summary": "Three-vendor parallel ideation (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check; produces BRAINSTORM.md."},
./z-harness/archive/tasks/T005/review.response.md:2763:+    "Cross-LLM consult agents are always referenced as consultant-primary and consultant-secondary; code review uses the reviewer agent.",
./z-harness/archive/tasks/T005/review.response.md:2793:consultant-primary.md
./z-harness/archive/tasks/T005/review.response.md:2835:docs/human/mr-reviewer.md:10:The review fans out to all available LLM voices (Claude Sonnet inline, plus the configured `consultant-primary` and `consultant-secondary` providers). Findings are deduplicated, tagged by which voices raised them, ranked P0–P4, and written to `z-harness/<slug>/MR-REVIEW.md` in `TASKS.md`-compatible shape. The command **never blocks** — you triage by deleting unwanted findings from MR-REVIEW.md, then run `/z-implement-all --tasks=z-harness/<slug>/MR-REVIEW.md` on survivors.
./z-harness/archive/tasks/T005/review.response.md:3078: M agents/consultant-primary.md
./z-harness/archive/portable-harness-final-review/transcripts/001-final-review-2pronged.md:13:- File: `agents/consultant-primary.md` — Reason: SPEC §Consultant + reviewer agents — generalized dispatch replaces `gemini-consultant`; without this canonical agent, all `subagent_type="consultant-primary"` call sites fail.
./z-harness/archive/portable-harness-final-review/transcripts/001-final-review-2pronged.md:71:- All three new canonical agents (consultant-primary, consultant-secondary, reviewer) are missing.
./z-harness/archive/lookup-subagent-brainstorm/transcripts/001-codex-brainstorm.prompt.md:18:- **consultant-primary/secondary** (Sonnet): proxy to Gemini/Codex LLMs. No domain APIs.
./z-harness/archive/20260524T184351Z-lookup-subagent/transcripts/001-gemini-brainstorm.prompt.md:18:- consultant-primary/secondary (Sonnet): proxy to Gemini/Codex LLMs. No domain APIs.

exec
/bin/zsh -lc "nl -ba z-harness/plans/tiered-quality-uplift/SPEC.md | sed -n '97,116p'" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "nl -ba commands/z-uplift.md | sed -n '698,999p'" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "nl -ba commands/z-audit.md | sed -n '136,150p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
   698	
   699	## Phase 2 — Cross-cutting pass
   700	
   701	Record `T0=$(date +%s%3N)` at phase start.
   702	
   703	If `CROSS_CUTTING_SKIP=true`:
   704	
   705	```bash
   706	cat > "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" <<'EOF'
   707	# Cross-cutting findings — (skipped)
   708	
   709	Cross-cutting pass was skipped via --cross-cutting=skip.
   710	EOF
   711	cp "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase2-cross-cutting.md"
   712	WALL_MS=$(( $(date +%s%3N) - T0 ))
   713	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
   714	  "$(printf '{"phase":2,"name":"cross-cutting","wall_ms":%d,"user_wait_ms":0,"skipped":true}' "$WALL_MS")"
   715	```
   716	
   717	Then skip to Phase 3.
   718	
   719	### Step 1 — Build source map
   720	
   721	Curate a source map of up to ~100 paths: the top-50 files by churn over the last 90 days (filtered to paths that still exist on disk), UNION the entry file for each component.
   722	
   723	```bash
   724	SOURCE_MAP_JSON="$(python3 - "$Z_HARNESS_PLAN_DIR" "$COMPONENTS_JSON" "$(pwd)" <<'PYEOF'
   725	import os, sys, json, subprocess
   726	
   727	plan_dir     = sys.argv[1]
   728	data         = json.loads(sys.argv[2])
   729	repo_root    = sys.argv[3]
   730	components   = data["components"]
   731	
   732	# --- churn top-50 (paths still present on disk) ---
   733	result = subprocess.run(
   734	    ["git", "log", "--since=90 days ago", "--name-only", "--format="],
   735	    capture_output=True, text=True, cwd=repo_root
   736	)
   737	from collections import Counter
   738	counts = Counter()
   739	for line in result.stdout.splitlines():
   740	    line = line.strip()
   741	    if line:
   742	        counts[line] += 1
   743	
   744	churn_paths = []
   745	for path, _ in counts.most_common(200):
   746	    abs_path = os.path.join(repo_root, path)
   747	    if os.path.isfile(abs_path):
   748	        churn_paths.append(path)
   749	    if len(churn_paths) >= 50:
   750	        break
   751	
   752	# --- entry-file heuristic per component ---
   753	def entry_file(comp_path, repo_root):
   754	    """Return relative path of entry file for this component (first match wins)."""
   755	    abs_comp = os.path.join(repo_root, comp_path) if not os.path.isabs(comp_path) else comp_path
   756	    candidates = [
   757	        os.path.join(abs_comp, "README.md"),
   758	        os.path.join(abs_comp, "src", "lib.rs"),
   759	        os.path.join(abs_comp, "src", "main.rs"),
   760	        os.path.join(abs_comp, "__init__.py"),
   761	        os.path.join(abs_comp, "package.json"),
   762	    ]
   763	    for c in candidates:
   764	        if os.path.isfile(c):
   765	            return os.path.relpath(c, repo_root)
   766	    # first non-test source file lexicographically
   767	    try:
   768	        for fname in sorted(os.listdir(abs_comp)):
   769	            if fname.startswith("test") or fname.startswith("_test") or fname.endswith("_test.py"):
   770	                continue
   771	            full = os.path.join(abs_comp, fname)
   772	            if os.path.isfile(full):
   773	                return os.path.relpath(full, repo_root)
   774	    except OSError:
   775	        pass
   776	    # fall back to component root path itself
   777	    return comp_path
   778	
   779	entry_paths = []
   780	for c in components:
   781	    ep = entry_file(c["path"], repo_root)
   782	    if ep and os.path.isfile(os.path.join(repo_root, ep)):
   783	        entry_paths.append(ep)
   784	
   785	# merge, de-duplicate, cap at ~100
   786	seen = set()
   787	merged = []
   788	for p in churn_paths + entry_paths:
   789	    if p not in seen:
   790	        seen.add(p)
   791	        merged.append(p)
   792	    if len(merged) >= 100:
   793	        break
   794	
   795	print(json.dumps(merged))
   796	PYEOF
   797	)"
   798	```
   799	
   800	### Step 2 — Load STYLE.md content (if applicable)
   801	
   802	```bash
   803	if [ "$NO_STYLE" != "true" ] && [ -f "$STYLE_MD_PATH" ]; then
   804	  STYLE_CONTENT="$(cat "$STYLE_MD_PATH")"
   805	else
   806	  STYLE_CONTENT=""
   807	fi
   808	```
   809	
   810	### Step 3 — Build prompt body
   811	
   812	```bash
   813	COMPONENTS_MD_CONTENT="$(cat "$Z_HARNESS_PLAN_DIR/COMPONENTS.md")"
   814	SOURCE_MAP_PATHS="$(python3 -c 'import json,sys; paths=json.loads(sys.argv[1]); print("\n".join(paths))' "$SOURCE_MAP_JSON")"
   815	
   816	CROSS_CUTTING_PROMPT="MODE: cross-cutting-uplift
   817	
   818	repo_root: $(pwd)
   819	slug: $SLUG
   820	
   821	components:
   822	$COMPONENTS_MD_CONTENT
   823	
   824	source_map (files to examine — top-50 by churn over last 90 days plus component entry files):
   825	$SOURCE_MAP_PATHS
   826	$([ -n "$STYLE_CONTENT" ] && printf '\nSTYLE.md:\n%s\n' "$STYLE_CONTENT" || true)
   827	Instructions: Examine the source map files for cross-component issues. For each finding, emit an explicit \`component: <slug-from-MANIFEST>\` marker (use the exact slug from the components table, or \`component: global\` for issues spanning all components). Then classify each finding as one of:
   828	- \`global-task\` — cross-component issues requiring a dedicated plan (duplicated abstractions, global API drift, cross-cutting architectural debt)
   829	- \`per-component-context\` — issues that should inform the per-component audit for that specific component
   830	- \`risk\` — watch items with no immediately actionable fix
   831	
   832	Style-drift findings must cite STYLE rule IDs explicitly.
   833	Number global-task findings G-001, G-002, ... (include affected files). Number per-component-context findings C-001, C-002, .... Number risk findings R-001, R-002, ...."
   834	```
   835	
   836	### Step 4 — Dispatch consultants in parallel
   837	
   838	Dispatch `consultant-primary` and `consultant-secondary` in a single message (two `Agent(...)` calls):
   839	
   840	```
   841	Agent(
   842	  subagent_type="consultant-primary",
   843	  description="Cross-cutting uplift (primary) for <slug>",
   844	  prompt="<CROSS_CUTTING_PROMPT>"
   845	)
   846	Agent(
   847	  subagent_type="consultant-secondary",
   848	  description="Cross-cutting uplift (secondary) for <slug>",
   849	  prompt="<CROSS_CUTTING_PROMPT>"
   850	)
   851	```
   852	
   853	Archive both transcripts:
   854	
   855	```bash
   856	echo "$PRIMARY_TRANSCRIPT"   > "$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts/phase2-consultant-primary.md"
   857	echo "$SECONDARY_TRANSCRIPT" > "$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts/phase2-consultant-secondary.md"
   858	```
   859	
   860	### Step 5 — Merge findings into CROSS-CUTTING.md
   861	
   862	Merge both consultant returns. For any finding missing a classification, default it to `per-component-context`.
   863	
   864	Write `$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md`:
   865	
   866	```markdown
   867	# Cross-cutting findings — <slug>
   868	
   869	## Global tasks (need dedicated plan)
   870	- G-001 — [HIGH] <subject> — component: <slug> — files: a, b, c
   871	...
   872	
   873	## Per-component context (inform audits)
   874	- C-001 — component: <slug> — <context>
   875	...
   876	
   877	## Risks (watch items)
   878	- R-001 — component: <slug> — <subject> — <evidence>
   879	...
   880	```
   881	
   882	Every finding must carry a `component: <slug>` marker. Unclassified findings are placed in the "Per-component context" section.
   883	
   884	### Step 6 — Create synthetic cross-cutting plan (if global-task count > 0)
   885	
   886	Count `G_COUNT` (number of `G-NNN` entries in CROSS-CUTTING.md).
   887	
   888	If `G_COUNT > 0`:
   889	
   890	```bash
   891	CROSS_DIR="$(dirname "$Z_HARNESS_PLAN_DIR")/${Z_HARNESS_SLUG}-cross-cutting"
   892	mkdir -p "$CROSS_DIR"
   893	```
   894	
   895	Write `$CROSS_DIR/SPEC.md`:
   896	
   897	```markdown
   898	# Spec — <slug>-cross-cutting
   899	
   900	This synthetic component addresses global-task findings from the cross-cutting pass.
   901	
   902	See: <abs path to CROSS-CUTTING.md>
   903	```
   904	
   905	Write `$CROSS_DIR/PLAN.md`:
   906	
   907	```markdown
   908	# Plan — <slug>-cross-cutting
   909	
   910	Implement each global-task finding (G-001, G-002, ...) as a separate task.
   911	Findings are sourced from CROSS-CUTTING.md.
   912	```
   913	
   914	Generate `$CROSS_DIR/TASKS.md` — one task per G-NNN entry. Parse the G-NNN lines from CROSS-CUTTING.md to extract the subject and affected files:
   915	
   916	```bash
   917	python3 - "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" "$CROSS_DIR/TASKS.md" "$Z_HARNESS_PLAN_DIR" <<'PYEOF'
   918	import re, sys
   919	
   920	cc_path   = sys.argv[1]
   921	tasks_out = sys.argv[2]
   922	plan_dir  = sys.argv[3]
   923	
   924	with open(cc_path) as f:
   925	    content = f.read()
   926	
   927	# Extract G-NNN lines from the Global tasks section
   928	global_section = re.search(
   929	    r'## Global tasks.*?\n(.*?)(?=\n## |\Z)', content, re.DOTALL
   930	)
   931	tasks_lines = []
   932	if global_section:
   933	    for line in global_section.group(1).splitlines():
   934	        m = re.match(r'-\s+(G-\d+)\s+[—-]+\s+(?:\[.*?\]\s+)?(.*?)(?:\s+[—-]+\s+files?:\s*(.*))?$', line.strip())
   935	        if m:
   936	            gnum    = m.group(1)
   937	            subject = m.group(2).strip() if m.group(2) else line.strip()
   938	            files   = m.group(3).strip() if m.group(3) else ""
   939	            files_line = f"  - {files}" if files else "  - (see CROSS-CUTTING.md)"
   940	            tasks_lines.append(
   941	                f"### [{gnum}] {subject}\n"
   942	                f"- **Files:**\n{files_line}\n"
   943	                f"- **Depends on:** (none)\n"
   944	                f"- **Acceptance:** Resolve the cross-cutting issue described in {plan_dir}/CROSS-CUTTING.md#{gnum}.\n"
   945	            )
   946	
   947	header = "# Tasks — cross-cutting global tasks\n\nGenerated from CROSS-CUTTING.md global-task findings.\n\n"
   948	with open(tasks_out, "w") as f:
   949	    f.write(header + "\n".join(tasks_lines) + "\n")
   950	print(f"wrote {tasks_out} with {len(tasks_lines)} task(s)")
   951	PYEOF
   952	```
   953	
   954	Insert `<slug>-cross-cutting` as the FIRST row in MANIFEST.md:
   955	
   956	```bash
   957	python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_SLUG" "$CROSS_DIR" <<'PYEOF'
   958	import sys, re
   959	
   960	manifest_path = sys.argv[1]
   961	slug          = sys.argv[2]
   962	cross_dir     = sys.argv[3]
   963	
   964	with open(manifest_path) as f:
   965	    content = f.read()
   966	
   967	cross_slug = f"{slug}-cross-cutting"
   968	new_row = f"| [ ] pending | {cross_slug} | (global) | — | — | {cross_dir}/TASKS.md |\n"
   969	
   970	# Insert immediately after the header row separator line
   971	content = re.sub(
   972	    r'(\|[-| ]+\|\n)',
   973	    r'\1' + new_row,
   974	    content,
   975	    count=1
   976	)
   977	with open(manifest_path, "w") as f:
   978	    f.write(content)
   979	print(f"inserted {cross_slug} as first row in MANIFEST.md")
   980	PYEOF
   981	```
   982	
   983	### Step 7 — Emit telemetry and checkpoint
   984	
   985	```bash
   986	G_COUNT="$(grep -c '^- G-' "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" 2>/dev/null || echo 0)"
   987	C_COUNT="$(grep -c '^- C-' "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" 2>/dev/null || echo 0)"
   988	R_COUNT="$(grep -c '^- R-' "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" 2>/dev/null || echo 0)"
   989	
   990	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cross_cutting_classified \
   991	  "$(printf '{"slug":"%s","global_tasks":%d,"per_component_context":%d,"risks":%d}' \
   992	     "$SLUG" "$G_COUNT" "$C_COUNT" "$R_COUNT")"
   993	
   994	cp "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase2-cross-cutting.md"
   995	WALL_MS=$(( $(date +%s%3N) - T0 ))
   996	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
   997	  "$(printf '{"phase":2,"name":"cross-cutting","wall_ms":%d,"user_wait_ms":%d}' \
   998	     "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
   999	```

 succeeded in 0ms:
   136	```
   137	Agent(
   138	  subagent_type="consultant-primary",
   139	  description="Audit findings review (Gemini) for <slug>",
   140	  prompt="MODE: audit-review\n\nA target has been audited across <dimensions>. Here is the full REPORT:\n\n<paste REPORT.md>\n\nTwo asks:\n1. What significant findings are MISSING — issues the dimension auditors should have caught but didn't?\n2. Which listed findings are TRIVIAL or speculative and should be dropped before promotion to TASKS.md?\n\nBe specific. Cite path:line. Severity-rank any additions."
   141	)
   142	Agent(
   143	  subagent_type="consultant-secondary",
   144	  description="Audit findings review (Codex) for <slug>",
   145	  prompt="MODE: audit-review\n\n<same prompt body>"
   146	)
   147	```
   148	
   149	Both transcripts archive themselves under `$BASE/archive/$RUN/transcripts/`.
   150	

 succeeded in 0ms:
    97	### Cross-cutting pass (`commands/z-uplift.md` Phase 2)
    98	Dispatch shape (bare agent names — providers are resolved at dispatch by `scripts/resolve-provider.sh`, NOT hardcoded to Gemini/Codex):
    99	```
   100	Agent(subagent_type="consultant-primary", description="Cross-cutting (primary) for <slug>",
   101	      prompt="MODE: cross-cutting-uplift\nrepo_root: <abs>\ncomponents: <COMPONENTS.md verbatim>\nsource_map: <top-50 files by churn over last 90 days, plus each component's entry file (heuristic below)>\nAsk: list cross-component issues (duplicated abstractions, style drift, dead code at module boundaries, public-API drift). For each, emit an explicit `component: <slug-from-MANIFEST>` marker, then classify as global-task | per-component-context | risk.")
   102	Agent(subagent_type="consultant-secondary", description="Cross-cutting (secondary) for <slug>", prompt="<same body>")
   103	```
   104	
   105	**Entry-file heuristic per component** (used in `source_map` above): pick the first match, in this order: `README.md` in component root → `src/lib.rs` → `src/main.rs` → `__init__.py` → `package.json` → first non-test source file by lexicographic order → component root path itself (if no source file detected).
   106	
   107	Merge into `CROSS-CUTTING.md`:
   108	```markdown
   109	# Cross-cutting findings — <slug>
   110	## Global tasks (need dedicated plan)
   111	- G-001 — [HIGH] <subject> — files: a, b, c
   112	## Per-component context (inform audits)
   113	- C-001 — affects <component-name> — <context>
   114	## Risks (watch items)
   115	- R-001 — <subject> — <evidence>
   116	```

exec
/bin/zsh -lc "nl -ba z-harness/plans/tiered-quality-uplift/SPEC.md | sed -n '116,132p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
   116	```
   117	
   118	If `global-task` count > 0 → synthetic component `<slug>-cross-cutting` inserted at top of MANIFEST. Its TASKS.md is hand-written from `global-task` entries (one task per G-NNN), with `**Files:**` lines aggregating affected paths.
   119	
   120	### Per-component audit (`commands/z-uplift.md` Phase 3)
   121	For each component in MANIFEST `pending` state:
   122	1. Mark MANIFEST state `[~] auditing` IMMEDIATELY before dispatch (so an interrupt mid-audit is detectable by resume logic).
   123	2. Dispatch one `auditor` subagent per `--dimensions` value in parallel. Prompt fields: `target_path`, `dimension`, `cross_cutting_context` (the verbatim `per-component-context` entries from CROSS-CUTTING.md whose `component:` marker matches this component's MANIFEST slug — exact slug match, NOT free-text), and `rubric_path` (set to absolute path of `./STYLE.md` when dimension ∈ {`cleanliness`, `design`} AND STYLE.md is present AND `--no-style` was NOT passed; empty string otherwise so the auditor falls back to its generic-dimension rubric). The auditor reads STYLE.md itself — never inline the file's content into the prompt.
   124	3. Merge per-dimension findings into `<slug>-<component>/REPORT.md`.
   125	4. Bundled consult: `consultant-primary` + `consultant-secondary` in parallel on REPORT.md (drops + additions). Same shape as `/z-audit` Phase 4.
   126	5. Auto-bail check: count CRITICAL+HIGH and total findings. If >10 CRIT-HIGH OR >30 total → mark MANIFEST `[!] bailed: crit_high_volume` (or `bailed: spec_problem` for STATUS: spec_problem from auditor); write partial REPORT.md; run cheap text-grep `git grep -l "<component-basename>"` across other components, append a "Potential dependents (text-grep — incomplete; validate manually for critical APIs)" section to REPORT.md and to MANIFEST.md's `Dependents warnings` section; skip TASKS.md generation; continue to next component.
   127	6. Otherwise: promote findings to `<slug>-<component>/TASKS.md` in `/z-implement-all`-consumable format. Write minimal SPEC.md + PLAN.md.
   128	7. Dispatch one `reviewer` over the generated TASKS.md (mandatory safety gate). On `Blocker`, re-edit in-place.
   129	8. Mark MANIFEST state `[a] audited`.
   130	
   131	### Sequential implement (`commands/z-uplift.md` Phase 5)
   132	For each component with state `[a] audited`:

codex
I found the implementation is in the command prompt file rather than a shell script. The main risks are therefore prompt-level gaps that will cause the operator/agent to do the wrong thing or generate malformed artifacts.
exec
/bin/zsh -lc "nl -ba commands/z-uplift.md | sed -n '1000,1095p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
  1000	
  1001	---
  1002	
  1003	## Phase 3 — Per-component audits
  1004	
  1005	**Full implementation lands in T004 — this is a placeholder describing the expected behavior.**
  1006	
  1007	For each component in MANIFEST `pending` state (processing synthetic `<slug>-cross-cutting` first if it exists):
  1008	
  1009	1. Mark MANIFEST state `[~] auditing` immediately before dispatch.
  1010	2. Dispatch one `auditor` subagent per `--dimensions` value in parallel. Inject `rubric_path` (absolute path of `./STYLE.md`) for `cleanliness` and `design` dimensions when STYLE.md is present and `NO_STYLE` is not set. Inject `cross_cutting_context` from CROSS-CUTTING.md entries matching this component's MANIFEST slug (exact match).
  1011	3. Merge per-dimension findings into `<slug>-<component>/REPORT.md`.
  1012	4. Dispatch bundled `consultant-primary` + `consultant-secondary` consult in parallel on REPORT.md (drops + additions).
  1013	5. Auto-bail check: if `>10 CRIT-HIGH` OR `>30 total` findings → mark MANIFEST `[!] bailed: crit_high_volume`; run `git grep -l "<component-basename>"` across other components; append "Potential dependents (text-grep — incomplete; validate manually for critical APIs)" to REPORT.md and MANIFEST.md; skip TASKS.md generation; continue to next component.
  1014	6. Otherwise: promote findings to `<slug>-<component>/TASKS.md`; write minimal SPEC.md + PLAN.md.
  1015	7. Dispatch one `reviewer` over generated TASKS.md (mandatory safety gate). On Blocker, re-edit in-place.
  1016	8. Mark MANIFEST state `[a] audited`.
  1017	
  1018	Emit `component_audit_start` / `component_audit_done` telemetry per component.
  1019	
  1020	Checkpoint: `phase3-audits.md`.
  1021	
  1022	---
  1023	
  1024	## Phase 4 — Review gate
  1025	
  1026	Present an aggregated queue summary to the user before any implementation begins:
  1027	
  1028	```
  1029	Uplift queue summary for <slug>:
  1030	  Components audited:   N
  1031	  Total tasks queued:   N
  1032	  Bailed components:    N (list)
  1033	  Dep warnings:         N
  1034	
  1035	Proceed to sequential implementation? [yes / abort]
  1036	```
  1037	
  1038	Use `AskUserQuestion` for this gate. If user aborts, emit `run_end status: aborted_by_user` and exit.
  1039	
  1040	Checkpoint: `phase4-review-gate.md`.
  1041	
  1042	---
  1043	
  1044	## Phase 5 — Sequential implement
  1045	
  1046	**Full implementation lands in T005 — this is a placeholder describing the expected behavior.**
  1047	
  1048	For each component with state `[a] audited` in MANIFEST order (synthetic `<slug>-cross-cutting` first):
  1049	
  1050	1. AskUser gate: proceed with this component / skip this component / abort uplift.
  1051	2. If proceed: mark MANIFEST `[i] implementing`; invoke `/z-implement-all --tasks=z-harness/plans/<slug>-<component>/TASKS.md`; wait for completion; mark MANIFEST `[x] done`.
  1052	3. If skip: mark MANIFEST `[s] skipped: user`; continue to next component.
  1053	4. If abort: leave remaining component states unchanged; emit `run_end status: aborted_by_user`; exit.
  1054	
  1055	On re-invoke with a component in `[i] implementing` state (interrupted mid-implement): AskUser — resume with `/z-implement-all` on this component / mark `[s] skipped` / mark `[x] done` (if completed manually) / abort.
  1056	
  1057	Emit `component_implement_start` / `component_implement_done` telemetry per component.
  1058	
  1059	Checkpoint: `phase5-implement.md`.
  1060	
  1061	---
  1062	
  1063	## Phase 6 — Finalize
  1064	
  1065	Phase 6 closes the uplift run by recording final telemetry, notifying the user with a summary of outcomes (done / skipped / bailed), and flagging any follow-on work. It logs `run_end` with a structured status blob so post-run analysis can compute per-run metrics. If any task in any generated TASKS.md carried a `**DOCS:**` line, Phase 6 surfaces a recommendation to run `/z-maintain-docs` — this keeps the two-tier documentation current after uplift-driven code changes. No code is modified in this phase.
  1066	
  1067	1. Log `run_end` with a status blob:
  1068	
  1069	```bash
  1070	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_end \
  1071	  "$(printf '{"slug":"%s","status":"complete","components_done":%d,"components_skipped":%d,"components_bailed":%d}' \
  1072	     "$SLUG" "$DONE_COUNT" "$SKIPPED_COUNT" "$BAILED_COUNT")"
  1073	```
  1074	
  1075	2. Push-notify the user with the final summary (done / skipped / bailed counts).
  1076	
  1077	3. If any task in any generated TASKS.md carried a `**DOCS:**` line, recommend:
  1078	
  1079	   > "Some tasks carried DOCS tags. Run `/z-maintain-docs` to refresh the two-tier documentation."
  1080	
  1081	Checkpoint: `phase6-finalize.md`.

codex
Blockers/majors:

- **Major — `commands/z-uplift.md:703-717`**: The skip path relies on prose for control flow, so a literal/stepwise executor can still run source-map, dispatch, synthetic-dir, and telemetry steps after writing the skipped placeholder. Make the skip branch explicit: write the placeholder, archive/log it, emit any required skip telemetry, then `continue to Phase 3` with a clear “do not execute Steps 1-7” guard or wrap the rest in an `else`.

- **Major — `commands/z-uplift.md:860-882`**: The merge/classification step is underspecified and has no deterministic logic to actually create `CROSS-CUTTING.md`, enforce `component:` markers, or default unclassified findings to per-component context. Add a concrete merge procedure or script that consumes both transcripts, normalizes into the three required sections, inserts/defaults missing classifications, and rejects/repairs findings without `component:`.

- **Major — `commands/z-uplift.md:776-783`**: The entry-file fallback to the component root is dropped because `entry_paths` only appends paths passing `os.path.isfile`, so components with no matching file disappear from the source map. Track whether `entry_file()` returned a file or fallback root, and allow the root path through with `os.path.exists`/`os.path.isdir`.

- **Major — `commands/z-uplift.md:766-773`**: The “first non-test source file” heuristic only scans top-level files and accepts any non-test file, so it can pick `LICENSE`/docs and miss real nested source files. Implement a lexicographic recursive scan restricted to source extensions and excluding common test paths/names.

- **Major — `commands/z-uplift.md:884-892`**: Step 6 gates on `G_COUNT > 0`, but there is no pre-gate command assigning `G_COUNT`; the only concrete count happens later after the synthetic plan step. Move a robust `G_COUNT` calculation before the `if` and use that same value for synthetic-dir creation.

- **Major — `commands/z-uplift.md:933-939`**: The `TASKS.md` parser usually fails to extract `files:` when the line also contains `component:` because the optional files group can be skipped and the subject captures the rest of the line. Parse dash-separated fields explicitly, or match `files?:` independently after extracting `G-NNN` and subject.

- **Major — `commands/z-uplift.md:957-980`**: MANIFEST insertion is not idempotent, so rerunning/resuming Phase 2 with globals will insert duplicate `<slug>-cross-cutting` rows. Check for an existing row with that slug first and update/skip insertion instead of blindly adding a new first row.

- **Major — `commands/z-uplift.md:986-988`**: `grep -c ... || echo 0` produces `0\n0` when there are no matches because `grep -c` prints `0` and exits nonzero, which can break numeric `printf` telemetry. Use `grep -c ... || true`, or compute all three counts in Python and print valid integers only.
tokens used
68,127
Blockers/majors:

- **Major — `commands/z-uplift.md:703-717`**: The skip path relies on prose for control flow, so a literal/stepwise executor can still run source-map, dispatch, synthetic-dir, and telemetry steps after writing the skipped placeholder. Make the skip branch explicit: write the placeholder, archive/log it, emit any required skip telemetry, then `continue to Phase 3` with a clear “do not execute Steps 1-7” guard or wrap the rest in an `else`.

- **Major — `commands/z-uplift.md:860-882`**: The merge/classification step is underspecified and has no deterministic logic to actually create `CROSS-CUTTING.md`, enforce `component:` markers, or default unclassified findings to per-component context. Add a concrete merge procedure or script that consumes both transcripts, normalizes into the three required sections, inserts/defaults missing classifications, and rejects/repairs findings without `component:`.

- **Major — `commands/z-uplift.md:776-783`**: The entry-file fallback to the component root is dropped because `entry_paths` only appends paths passing `os.path.isfile`, so components with no matching file disappear from the source map. Track whether `entry_file()` returned a file or fallback root, and allow the root path through with `os.path.exists`/`os.path.isdir`.

- **Major — `commands/z-uplift.md:766-773`**: The “first non-test source file” heuristic only scans top-level files and accepts any non-test file, so it can pick `LICENSE`/docs and miss real nested source files. Implement a lexicographic recursive scan restricted to source extensions and excluding common test paths/names.

- **Major — `commands/z-uplift.md:884-892`**: Step 6 gates on `G_COUNT > 0`, but there is no pre-gate command assigning `G_COUNT`; the only concrete count happens later after the synthetic plan step. Move a robust `G_COUNT` calculation before the `if` and use that same value for synthetic-dir creation.

- **Major — `commands/z-uplift.md:933-939`**: The `TASKS.md` parser usually fails to extract `files:` when the line also contains `component:` because the optional files group can be skipped and the subject captures the rest of the line. Parse dash-separated fields explicitly, or match `files?:` independently after extracting `G-NNN` and subject.

- **Major — `commands/z-uplift.md:957-980`**: MANIFEST insertion is not idempotent, so rerunning/resuming Phase 2 with globals will insert duplicate `<slug>-cross-cutting` rows. Check for an existing row with that slug first and update/skip insertion instead of blindly adding a new first row.

- **Major — `commands/z-uplift.md:986-988`**: `grep -c ... || echo 0` produces `0\n0` when there are no matches because `grep -c` prints `0` and exits nonzero, which can break numeric `printf` telemetry. Use `grep -c ... || true`, or compute all three counts in Python and print valid integers only.
