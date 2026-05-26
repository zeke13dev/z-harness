You are reviewing code that Claude just wrote for task T005: Implement Phase 4 (review gate) + Phase 5 (sequential implement loop).

Spec (excerpt from SPEC.md, Phase 4 & 5 contract):

**Phase 4 — Review gate** (L36-37):
Present the aggregated queue summary to user (component count, total tasks, bailed components, dep warnings). Informational only; no AskUser gate.

**Phase 5 — Sequential implement** (L130-138):
For each component with state `[a] audited`:
1. AskUser: proceed / skip this component / abort uplift.
2. If proceed: invoke `/z-implement-all --tasks=z-harness/plans/<slug>-<component>/TASKS.md`. Wait for completion.
3. On completion: mark MANIFEST `[x] done`.
4. On user-skip: mark MANIFEST `[s] skipped: user`.
5. On abort: mark MANIFEST state for this and remaining components left unchanged; log `run_end status: aborted_by_user`; exit.

Synthetic `<slug>-cross-cutting` is processed FIRST so any global-task API changes land before per-component cleanup.

Acceptance criteria:
- synthetic cross-cutting component is processed first (or skipped cleanly if absent)
- per-component AskUser gates work
- MANIFEST state transitions are atomic per component
- abort leaves remaining MANIFEST rows unchanged

Diff (primary artifact — focus scrutiny on what changed):

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
```

Step 3 issue: Line 1954 shows duplicate variable assignment: copies MANIFEST.md as the checkpoint but names it `phase4-review-gate.md` in archive when it should checkpoint the summary. Phase 4 Step 2 writes `phase4-review-gate.md` separately at Step 2 line 1901-1935.

## Phase 5 — Sequential implement

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

    # Synthetic cross-cutting goes first
    if row_slug.endswith('-cross-cutting') or comp == '(global)':
        cross_cutting_row = row
    else:
        other_rows.append(row)

ordered = ([cross_cutting_row] if cross_cutting_row else []) + other_rows
print(json.dumps(ordered))
PYEOF
)"
```

Phase 5 Step 1 correctly implements synthetic cross-cutting-first ordering: checks both slug endswith-cross-cutting and comp == '(global)' marker (2009-2011), with fallback [cross_cutting_row] if cross_cutting_row else [] ensuring clean skip if absent (2015).

### Step 2c — Dispatch implementation (key section)

Emit `component_implement_start` event and mark MANIFEST `[i] implementing` BEFORE dispatch (so an interrupt is detectable on next resume):

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" component_implement_start \
  "$(printf '{"component":"%s","tasks_md":"%s"}' "$COMP_SLUG" "$COMP_TASKS_MD")"

python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "[i] implementing" <<'PYEOF'
import re, sys, os

def manifest_write(path, content):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, path)

manifest_path = sys.argv[1]
comp_slug     = sys.argv[2]
new_state     = sys.argv[3]

with open(manifest_path) as f:
    content = f.read()

def replace_row(m):
    row   = m.group(0)
    cells = row.split('|')
    if len(cells) < 8:
        return row
    if cells[3].strip() != comp_slug:
        return row
    cells[1] = f" {new_state} "
    return '|'.join(cells)

pattern = re.compile(
    r'\|[^|\n]*\|\s*[^|\n]*\|\s*' + re.escape(comp_slug) + r'\s*\|[^\n]*\|',
    re.MULTILINE
)
updated = pattern.sub(replace_row, content)
manifest_write(manifest_path, updated)
print(f"marked {comp_slug} as {new_state}")
PYEOF
```

Present the `/z-implement-all` invocation command to the user and instruct them to run it:

> Run the following command to implement `<component>`:
>
> `/z-implement-all --tasks=<COMP_TASKS_MD>`
>
> When `/z-implement-all` completes, re-invoke `/z-uplift` to continue with the next component.

Then **exit** the current `/z-uplift` invocation cleanly (do not attempt to wait for `/z-implement-all` inline — it is a separate slash command that the user runs). The next `/z-uplift` invocation will detect the `[i] implementing` row and check completion via Step 2a above.

### Step 2e — Abort path

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

Scrutinize this code rigorously. Claude is prone to: over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope beyond the spec.

Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, and a suggested fix.

**OUTPUT BUDGET — respect strictly:**
- Total response under **8000 characters**.
- Report **blockers and majors only**. Skip minors and nits unless a "minor" hides a correctness bug — in which case promote it to major.
- One finding per bullet. Two sentences max per finding (one for the problem, one for the fix).
- No re-stating of code already in the diff. No summaries of what the code does. No restating the spec.

