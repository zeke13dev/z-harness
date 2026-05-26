2026-05-26T04:53:21.401471Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-26T04:53:21.402040Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-26T04:53:21.402042Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-26T04:53:21.402044Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-suggest-memory/SKILL.md: invalid YAML: did not find expected key at line 3 column 35, while parsing a block mapping
2026-05-26T04:53:21.402045Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-26T04:53:21.402047Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-26T04:53:21.402049Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.133.0
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR]
reasoning effort: medium
reasoning summaries: none
session id: 019e62a1-572e-7c20-ab26-7795eb7c4b29
--------
user
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


codex
I’ll inspect the actual changed files so the review is grounded in line-level context, then I’ll keep the output to blockers and majors only as requested.
exec
/bin/zsh -lc 'rg -n "Phase 4|Phase 5|phase4-review-gate|IMPL_QUEUE|component_implement_start|aborted_by_user|cross-cutting" -S .' in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc 'git status --short && git diff --stat' in /Users/zeke/dev/z-harness
 succeeded in 239ms:
 README.md                                          |   73 +-
 agents/consultant-primary.md                       |   20 +-
 agents/consultant-secondary.md                     |   20 +-
 agents/external-lookup.md                          |  151 +
 agents/implementer.md                              |   22 +-
 agents/reviewer.md                                 |   15 +-
 commands/z-audit.md                                |    9 +
 commands/z-brainstorm.md                           |   20 +
 commands/z-do.md                                   |   48 +-
 commands/z-implement-all.md                        |  267 +-
 commands/z-init-docs.md                            |   29 +-
 commands/z-maintain-docs.md                        |   40 +-
 commands/z-mr-review.md                            |   10 +
 commands/z-plan-light.md                           |   45 +-
 commands/z-plan-split.md                           |   29 +-
 commands/z-plan.md                                 |   41 +-
 commands/z-research.md                             |   20 +
 commands/z-review-all.md                           |  278 +-
 commands/z-stats.md                                |   12 +-
 commands/z-suggest-memory.md                       |   15 +-
 commands/z-update.md                               |   44 +-
 docs/human/skills.md                               |   40 +-
 docs/llm/INDEX.json                                |    4 +-
 docs/llm/multi-ide-exports.json                    |  187 +-
 docs/llm/skills.json                               |   42 +-
 docs/llm/z-update.json                             |   51 +-
 .../.agent/rules/z-harness-consultant-primary.md   |   20 +-
 .../.agent/rules/z-harness-consultant-secondary.md |   20 +-
 exports/agy/.agent/rules/z-harness-implementer.md  |   22 +-
 exports/agy/.agent/rules/z-harness-reviewer.md     |   15 +-
 exports/agy/.agent/skills/z-amend/SKILL.md         |    2 +
 exports/agy/.agent/skills/z-brainstorm/SKILL.md    |   20 +
 exports/agy/.agent/skills/z-do/SKILL.md            |   46 +-
 exports/agy/.agent/skills/z-implement-all/SKILL.md |  298 +-
 exports/agy/.agent/skills/z-init-docs/SKILL.md     |   29 +-
 exports/agy/.agent/skills/z-maintain-docs/SKILL.md |   40 +-
 exports/agy/.agent/skills/z-plan-light/SKILL.md    |   45 +-
 exports/agy/.agent/skills/z-plan-split/SKILL.md    |   29 +-
 exports/agy/.agent/skills/z-plan/SKILL.md          |   41 +-
 exports/agy/.agent/skills/z-research/SKILL.md      |   20 +
 exports/agy/.agent/skills/z-review-all/SKILL.md    |  262 +-
 exports/agy/.agent/skills/z-stats/SKILL.md         |   12 +-
 .../agy/.agent/skills/z-suggest-memory/SKILL.md    |   52 +
 exports/agy/.agent/workflows/z-audit.md            |    9 +
 exports/agy/.agent/workflows/z-brainstorm.md       |   20 +
 exports/agy/.agent/workflows/z-do.md               |   46 +-
 exports/agy/.agent/workflows/z-implement-all.md    |  267 +-
 exports/agy/.agent/workflows/z-init-docs.md        |   29 +-
 exports/agy/.agent/workflows/z-maintain-docs.md    |   40 +-
 exports/agy/.agent/workflows/z-mr-review.md        |   10 +
 exports/agy/.agent/workflows/z-plan-light.md       |   45 +-
 exports/agy/.agent/workflows/z-plan-split.md       |   29 +-
 exports/agy/.agent/workflows/z-plan.md             |   41 +-
 exports/agy/.agent/workflows/z-research.md         |   20 +
 exports/agy/.agent/workflows/z-review-all.md       |  278 +-
 exports/agy/.agent/workflows/z-stats.md            |   12 +-
 exports/agy/.agent/workflows/z-suggest-memory.md   |   13 +
 exports/agy/.agent/workflows/z-update.md           |   44 +-
 exports/agy/agy-plugin.yaml                        |   31 +-
 exports/agy/prompts/consultant-primary.md          |   20 +-
 exports/agy/prompts/consultant-secondary.md        |   20 +-
 exports/agy/prompts/implementer.md                 |   22 +-
 exports/agy/prompts/reviewer.md                    |   15 +-
 exports/agy/prompts/skill-z-amend.md               |    2 +
 exports/agy/prompts/skill-z-brainstorm.md          |   20 +
 exports/agy/prompts/skill-z-do.md                  |   46 +-
 exports/agy/prompts/skill-z-implement-all.md       |  298 +-
 exports/agy/prompts/skill-z-init-docs.md           |   29 +-
 exports/agy/prompts/skill-z-maintain-docs.md       |   40 +-
 exports/agy/prompts/skill-z-plan-light.md          |   45 +-
 exports/agy/prompts/skill-z-plan-split.md          |   29 +-
 exports/agy/prompts/skill-z-plan.md                |   41 +-
 exports/agy/prompts/skill-z-research.md            |   20 +
 exports/agy/prompts/skill-z-review-all.md          |  262 +-
 exports/agy/prompts/skill-z-stats.md               |   12 +-
 exports/agy/prompts/skill-z-suggest-memory.md      |   52 +
 exports/agy/prompts/z-audit.md                     |    9 +
 exports/agy/prompts/z-brainstorm.md                |   20 +
 exports/agy/prompts/z-do.md                        |   46 +-
 exports/agy/prompts/z-implement-all.md             |  267 +-
 exports/agy/prompts/z-init-docs.md                 |   29 +-
 exports/agy/prompts/z-maintain-docs.md             |   40 +-
 exports/agy/prompts/z-mr-review.md                 |   10 +
 exports/agy/prompts/z-plan-light.md                |   45 +-
 exports/agy/prompts/z-plan-split.md                |   29 +-
 exports/agy/prompts/z-plan.md                      |   41 +-
 exports/agy/prompts/z-research.md                  |   20 +
 exports/agy/prompts/z-review-all.md                |  278 +-
 exports/agy/prompts/z-stats.md                     |   12 +-
 exports/agy/prompts/z-suggest-memory.md            |   13 +
 exports/agy/prompts/z-update.md                    |   44 +-
 exports/codex/AGENTS.md                            |  461 ++-
 exports/codex/prompts/z-amend.md                   |    2 +
 exports/codex/prompts/z-audit.md                   |    9 +
 exports/codex/prompts/z-brainstorm.md              |   20 +
 exports/codex/prompts/z-do.md                      |   46 +-
 exports/codex/prompts/z-implement-all.md           |  298 +-
 exports/codex/prompts/z-init-docs.md               |   29 +-
 exports/codex/prompts/z-maintain-docs.md           |   40 +-
 exports/codex/prompts/z-mr-review.md               |   10 +
 exports/codex/prompts/z-plan-light.md              |   43 +-
 exports/codex/prompts/z-plan-split.md              |   29 +-
 exports/codex/prompts/z-plan.md                    |   41 +-
 exports/codex/prompts/z-research.md                |   20 +
 exports/codex/prompts/z-review-all.md              |  262 +-
 exports/codex/prompts/z-stats.md                   |   12 +-
 exports/codex/prompts/z-suggest-memory.md          |   52 +
 exports/codex/prompts/z-update.md                  |  135 +-
 .../cursor/.cursor/rules/consultant-primary.mdc    |   20 +-
 .../cursor/.cursor/rules/consultant-secondary.mdc  |   20 +-
 exports/cursor/.cursor/rules/implementer.mdc       |   22 +-
 exports/cursor/.cursor/rules/reviewer.mdc          |   15 +-
 exports/cursor/.cursor/rules/z-amend.mdc           |    2 +
 exports/cursor/.cursor/rules/z-audit.mdc           |    9 +
 exports/cursor/.cursor/rules/z-brainstorm.mdc      |   20 +
 exports/cursor/.cursor/rules/z-do.mdc              |   48 +-
 exports/cursor/.cursor/rules/z-implement-all.mdc   |  298 +-
 exports/cursor/.cursor/rules/z-init-docs.mdc       |   29 +-
 exports/cursor/.cursor/rules/z-maintain-docs.mdc   |   40 +-
 exports/cursor/.cursor/rules/z-mr-review.mdc       |   10 +
 exports/cursor/.cursor/rules/z-plan-light.mdc      |   45 +-
 exports/cursor/.cursor/rules/z-plan-split.mdc      |   29 +-
 exports/cursor/.cursor/rules/z-plan.mdc            |   41 +-
 exports/cursor/.cursor/rules/z-research.mdc        |   20 +
 exports/cursor/.cursor/rules/z-review-all.mdc      |  262 +-
 exports/cursor/.cursor/rules/z-stats.mdc           |   12 +-
 exports/cursor/.cursor/rules/z-suggest-memory.mdc  |   52 +
 exports/cursor/.cursor/rules/z-update.mdc          |  137 +-
 install.sh                                         |  250 +-
 scripts/check-timeout.sh                           |   83 +
 scripts/liveness.sh                                |  196 ++
 scripts/version.sh                                 |    7 +-
 skills/z-amend/SKILL.md                            |    3 +
 skills/z-brainstorm/SKILL.md                       |   21 +
 skills/z-debug/SKILL.md                            |    1 +
 skills/z-do/SKILL.md                               |   49 +-
 skills/z-implement-all/SKILL.md                    |  298 +-
 skills/z-improve/SKILL.md                          |    1 +
 skills/z-init-docs/SKILL.md                        |   29 +-
 skills/z-maintain-docs/SKILL.md                    |   40 +-
 skills/z-plan-light/SKILL.md                       |   46 +-
 skills/z-plan-split/SKILL.md                       |   30 +-
 skills/z-plan/SKILL.md                             |   42 +-
 skills/z-research/SKILL.md                         |   21 +
 skills/z-review-all/SKILL.md                       |  262 +-
 skills/z-stats/SKILL.md                            |   12 +-
 skills/z-suggest-memory/SKILL.md                   |   54 +-
 z-harness/archive/docs/events.jsonl                |   10 +
 z-harness/archive/orchestration/events.jsonl       |    2 +
 z-harness/archive/tasks/T001/events.jsonl          |   17 +
 z-harness/archive/tasks/T001/review.prompt.md      |  974 +++++-
 z-harness/archive/tasks/T001/review.response.md    | 1803 +++++++++-
 z-harness/archive/tasks/T002/events.jsonl          |   15 +
 z-harness/archive/tasks/T003/events.jsonl          |    8 +
 z-harness/archive/tasks/T003/review.prompt.md      |  714 ++--
 z-harness/archive/tasks/T003/review.response.md    | 1739 ++++++++--
 z-harness/archive/tasks/T004/events.jsonl          |   13 +
 z-harness/archive/tasks/T005/events.jsonl          |    2 +
 z-harness/archive/tasks/T006/events.jsonl          |    3 +
 z-harness/archive/tasks/T006/review.prompt.md      | 2725 ++++++++++++++-
 z-harness/archive/tasks/T006/review.response.md    | 3605 +++++++++++++++++++-
 z-harness/archive/tasks/T007/events.jsonl          |    3 +
 z-harness/archive/tasks/T008/events.jsonl          |    1 +
 z-harness/archive/tasks/T009/events.jsonl          |    1 +
 z-harness/archive/tasks/T012/events.jsonl          |    2 +
 z-harness/lookup-cache/.gitignore                  |    2 +
 z-harness/metrics.jsonl                            |  341 ++
 .../lookup-subagent/staging/qt-market-lookup.md    |  175 +
 168 files changed, 19475 insertions(+), 2080 deletions(-)

 succeeded in 242ms:
./z-harness/plans/mr-style-reviewer/archive/tasks/T014/review.response.md:1205:## Phase 4 — Cross-LLM Critique
./z-harness/plans/mr-style-reviewer/archive/tasks/T014/review.response.md:2513:## Phase 5 — User approval and write
./z-harness/plans/mr-style-reviewer/archive/tasks/T014/review.response.md:2544:- **re-critique** → loop back to Phase 4 with the current `REVISED_STYLE_MD` as input.
./z-harness/plans/mr-style-reviewer/archive/tasks/T014/review.response.md:3189:## Phase 4 — Final user message
./z-harness/plans/mr-style-reviewer/archive/tasks/T004/review.response.md:1047:./z-harness/brainstorm-and-research/TASKS.md:35:    - Phase 4: persist user choice into BRAINSTORM.md; `log-event.sh brainstorm_run_end`; push-notify with next-step recommendation.
./z-harness/plans/mr-style-reviewer/archive/tasks/T003/diff.patch:269:+## Phase 4 — Cross-LLM Critique
./z-harness/plans/mr-style-reviewer/archive/tasks/T003/diff.patch:317:+## Phase 5 — User approval and write
./z-harness/plans/mr-style-reviewer/archive/tasks/T003/diff.patch:348:+- **re-critique** → loop back to Phase 4 with the current `REVISED_STYLE_MD` as input.
./z-harness/plans/mr-style-reviewer/archive/tasks/T011/diff-v1.patch:263:+## Phase 4 — Cross-LLM Critique
./z-harness/plans/mr-style-reviewer/archive/tasks/T011/diff-v1.patch:311:+## Phase 5 — User approval and write
./z-harness/plans/mr-style-reviewer/archive/tasks/T011/diff-v1.patch:342:+- **re-critique** → loop back to Phase 4 with the current `REVISED_STYLE_MD` as input.
./research/hermes-agent/tests/docker/test_s6_profile_gateway_integration.py:11:→ unregister cycle is covered by Phase 4 once profile create/delete
./z-harness/plans/mr-style-reviewer/archive/tasks/T011/diff.patch:263:+## Phase 4 — Cross-LLM Critique
./z-harness/plans/mr-style-reviewer/archive/tasks/T011/diff.patch:311:+## Phase 5 — User approval and write
./z-harness/plans/mr-style-reviewer/archive/tasks/T011/diff.patch:342:+- **re-critique** → loop back to Phase 4 with the current `REVISED_STYLE_MD` as input.
./research/hermes-agent/tests/docker/test_profile_gateway.py:3:Phase 4 wires `hermes -p <profile> gateway start/stop` through the s6
./research/hermes-agent/tests/docker/test_profile_gateway.py:9:flip to plain ``test_…`` once Phase 4 lands (now).
./research/hermes-agent/tests/docker/test_container_restart.py:4:on every container restart. Phase 4 Task 4.0's container_boot module
./research/hermes-agent/tests/docker/test_container_restart.py:145:    # Create the profile + start its gateway. The Phase 4 hooks
./z-harness/plans/plan-decompose/SPEC.md:15:Not for: features with tight cross-cutting coupling, single-component refactors, anything `/z-plan-light` could handle.
./z-harness/plans/plan-decompose/SPEC.md:127:2. **medium**: file matches `.*\.(rs|py|ts|tsx|js|jsx)$` AND appears in ≥3 clusters (cross-cutting code module).
./z-harness/plans/plan-decompose/SPEC.md:181:- `STATUS: decision_needed` → halt only that cluster, parse the structured `decision_needed` payload, present to user via `AskUserQuestion` (using OPTIONS verbatim, RECOMMENDED_OPTION as the first option label), then re-spawn the cluster-planner with a resolution block injected into the prompt: `RESOLVED_DECISION: {decision_id, chosen_option, rationale}`. The re-spawn resumes from Phase 4 (skip Phase 0-3 — premise + exploration + decisions are settled). Sibling clusters continue (no global halt). Decision and resolution archived to `<root>/<cluster_slug>/archive/$RUN/decisions-late.md` AND echoed into MANIFEST under a `## Resolved decisions` section. MANIFEST tracks `attempts: <N>` and `final_status_at: <UTC ISO>` per cluster.
./z-harness/plans/plan-decompose/SPEC.md:185:If ALL clusters fail, halt with `total_cluster_failure` event. If ≥1 cluster succeeds, proceed to Phase 4 — partial trees are valid (user can run /z-implement-all on what completed, address failures separately).
./z-harness/plans/plan-decompose/SPEC.md:187:### Phase 4 — Reconciliation (file-overlap detection)
./z-harness/plans/plan-decompose/SPEC.md:199:### Phase 5 — Write MANIFEST.md + finalize
./z-harness/plans/plan-decompose/SPEC.md:263:### Phase 4 — Write SPEC.md + PLAN.md
./z-harness/plans/plan-decompose/SPEC.md:267:### Phase 5 — Write TASKS.md
./z-harness/plans/plan-decompose/SPEC.md:279:FILES_TOUCHED: [list of paths from TASKS.md]   # used by reconciliation Phase 4
./z-harness/plans/plan-decompose/TASKS.md:10:    - 6-phase contract from SPEC §"`cluster-planner` agent" implemented prose-completely: Phase 0 (anti-self-nesting + premise check), Phase 1 (exploration via doc-fetcher iff INDEX.json exists, else direct Read/Grep ≤10 files, NO Explore subagent), Phase 2 (identify ≤3 decisions, halt with `STATUS: decision_needed` if 4+ surface), Phase 3 (resolution with conservative-flagging rubric verbatim from SPEC: triggers a/b/c/d/e/f), Phase 4 (write SPEC.md + PLAN.md compressed — no consult section, no plan-review), Phase 5 (write TASKS.md with `complexity-classifier` subagent for stamping, same as /z-plan Phase 8), Phase 6 (return).
./z-harness/plans/plan-decompose/TASKS.md:13:    - Re-spawn semantics: on re-invocation with `RESOLVED_DECISION:` block in prompt, resume from Phase 4 (skip Phase 0-3).
./z-harness/plans/plan-decompose/TASKS.md:34:    - Phase 4 (Reconciliation): parse each cluster's TASKS.md `**Files:**` lines (canonical) AND validate against returned FILES_TOUCHED — disagreement → mark cluster `failed` + log `cluster_files_inconsistent`. Path normalization: workspace-relative, strip `./`, collapse `.`/`..`, normalize separator, reject escapes. Apply cascading severity heuristics (high > medium > low) per SPEC §"SHARED-CONCERNS.md schema". Files touched by exactly 1 cluster excluded.
./z-harness/plans/plan-decompose/TASKS.md:35:    - Phase 5 (Write artifacts): write `SHARED-CONCERNS.md` with frontmatter (`acknowledged: false`, `overlap_count`, `partial_tree: <bool>`). Write `MANIFEST.md` with cluster table, run-order, attempts tracking. Log `plan_split_run_end` with full payload. Push-notify with next-step recommendation.
./z-harness/plans/plan-decompose/archive/20260523T040951Z-plan-decompose/phase7-review-synthesis.md:9:1. **FILES_TOUCHED format + canonicality.** SPEC §"cluster-planner Phase 6" claims FILES_TOUCHED is "the reconciliation hook" while SPEC §"Phase 4" says main thread parses Files: from TASKS.md. Resolve: **TASKS.md is canonical.** FILES_TOUCHED is a JSON array of workspace-relative file paths returned by cluster-planner as a fast-path summary; main thread validates it against TASKS.md and fails the cluster if they disagree.
./z-harness/plans/plan-decompose/archive/20260523T040951Z-plan-decompose/phase7-review-synthesis.md:13:3. **Decision-gate re-spawn payload format.** When main thread resolves an escalated decision, the re-spawn prompt must contain a structured resolution block: `decision_id` (assigned by cluster-planner), `question`, `options`, `chosen_option`, `rationale`, `affected_files`. cluster-planner's re-invocation resumes from Phase 4 (skip Phase 0-3 since premise + exploration + decisions are settled).
./z-harness/plans/plan-decompose/archive/20260523T040951Z-plan-decompose/phase7-review-synthesis.md:51:4. §"Phase 4 — Reconciliation" — add path normalization rules.
./z-harness/plans/plan-decompose/archive/plan-decompose/transcripts/001-codex-plan-review.response.md:38:1. **Cluster-planner contract gap: undetectable bad decision escalation.** The conservative-flagging rule (Phase 3) says "if unsure whether a decision is non-obvious, escalate." But cluster-planner has no mechanism to detect when it *is* wrong about a decision even after making the call. If a leaf resolves a borderline decision poorly and doesn't flag it, the main thread's Phase 4 reconciliation (file-path overlap only) won't catch a semantic error — only a file collision. Severity?
./z-harness/plans/plan-decompose/archive/plan-decompose/transcripts/001-codex-plan-review.response.md:40:2. **SHARED-CONCERNS schema: overlaps from cluster-planner FILES_TOUCHED vs parsed TASKS.md.** SPEC Phase 4 says "main thread reads each cluster's TASKS.md and SPEC.md, extracts file paths from each task's `**Files:**` line." But the return value from cluster-planner Phase 6 includes `FILES_TOUCHED: [list of paths...]` as the reconciliation hook. Which is source of truth — re-parse TASKS.md or trust FILES_TOUCHED? If FILES_TOUCHED is a deduplicated summary vs. TASKS.md's per-task file list, a missing file in FILES_TOUCHED means zero overlap detection. Severity?
./z-harness/plans/plan-decompose/archive/plan-decompose/transcripts/001-codex-plan-review.response.md:44:4. **Ack-gate silent-pass on overlap_count: 0.** SPEC says if `overlap_count: 0`, SHARED-CONCERNS.md is written with `acknowledged: true` (auto-passes). But if a cluster-planner crashed mid-run and produced a partial TASKS.md with only 1 task, FILES_TOUCHED might spuriously show zero overlaps. The ack-gate auto-pass would hide a cluster-failure. Is the assumption that Phase 4 reconciliation can only run if all clusters returned STATUS: ok? Severity?
./z-harness/plans/plan-decompose/archive/plan-decompose/transcripts/001-codex-plan-review.response.md:46:5. **Phase 4 reconciliation timing: when does it read FILES_TOUCHED?** SPEC Phase 3 says "For each cluster-planner return: STATUS: ok → mark cluster ready." Then Phase 4 reads each cluster's outputs. But Phase 3 also handles decision_needed → re-spawn leaf, unable_to_complete → mark failed. If a leaf is re-spawned (decision gate resolved), Phase 4 must read the *second* return's FILES_TOUCHED, not the first. How does main thread track which return to read — archive/RUN/ glob pattern? Severity?
./z-harness/plans/plan-decompose/archive/plan-decompose/transcripts/001-codex-plan-review.response.md:83:The concern is valid only if reconciliation can run on partial or failed cluster outputs. If Phase 4 is gated strictly on all clusters returning `STATUS: ok` and finalized parsed `TASKS.md`, then `overlap_count: 0` auto-pass is acceptable.  
./z-harness/plans/plan-decompose/archive/plan-decompose/transcripts/001-codex-plan-review.response.md:135:The concern is valid only if reconciliation can run on partial or failed cluster outputs. If Phase 4 is gated strictly on all clusters returning `STATUS: ok` and finalized parsed `TASKS.md`, then `overlap_count: 0` auto-pass is acceptable.  
./z-harness/plans/plan-decompose/archive/plan-decompose/transcripts/001-codex-plan-review.prompt.md:23:1. **Cluster-planner contract gap: undetectable bad decision escalation.** The conservative-flagging rule (Phase 3) says "if unsure whether a decision is non-obvious, escalate." But cluster-planner has no mechanism to detect when it *is* wrong about a decision even after making the call. If a leaf resolves a borderline decision poorly and doesn't flag it, the main thread's Phase 4 reconciliation (file-path overlap only) won't catch a semantic error — only a file collision. Severity?
./z-harness/plans/plan-decompose/archive/plan-decompose/transcripts/001-codex-plan-review.prompt.md:25:2. **SHARED-CONCERNS schema: overlaps from cluster-planner FILES_TOUCHED vs parsed TASKS.md.** SPEC Phase 4 says "main thread reads each cluster's TASKS.md and SPEC.md, extracts file paths from each task's `**Files:**` line." But the return value from cluster-planner Phase 6 includes `FILES_TOUCHED: [list of paths...]` as the reconciliation hook. Which is source of truth — re-parse TASKS.md or trust FILES_TOUCHED? If FILES_TOUCHED is a deduplicated summary vs. TASKS.md's per-task file list, a missing file in FILES_TOUCHED means zero overlap detection. Severity?
./z-harness/plans/plan-decompose/archive/plan-decompose/transcripts/001-codex-plan-review.prompt.md:29:4. **Ack-gate silent-pass on overlap_count: 0.** SPEC says if `overlap_count: 0`, SHARED-CONCERNS.md is written with `acknowledged: true` (auto-passes). But if a cluster-planner crashed mid-run and produced a partial TASKS.md with only 1 task, FILES_TOUCHED might spuriously show zero overlaps. The ack-gate auto-pass would hide a cluster-failure. Is the assumption that Phase 4 reconciliation can only run if all clusters returned STATUS: ok? Severity?
./z-harness/plans/plan-decompose/archive/plan-decompose/transcripts/001-codex-plan-review.prompt.md:31:5. **Phase 4 reconciliation timing: when does it read FILES_TOUCHED?** SPEC Phase 3 says "For each cluster-planner return: STATUS: ok → mark cluster ready." Then Phase 4 reads each cluster's outputs. But Phase 3 also handles decision_needed → re-spawn leaf, unable_to_complete → mark failed. If a leaf is re-spawned (decision gate resolved), Phase 4 must read the *second* return's FILES_TOUCHED, not the first. How does main thread track which return to read — archive/RUN/ glob pattern? Severity?
./z-harness/plans/plan-decompose/archive/plan-decompose-v1/transcripts/001-gemini-plan-review.prompt.md:11:- Reconciliation Phase 4 detects file-path overlaps, applies deterministic severity heuristics, writes SHARED-CONCERNS.md with `acknowledged: false` default
./z-harness/plans/plan-decompose/archive/plan-decompose-v1/transcripts/001-gemini-plan-review.prompt.md:19:1. **cluster-planner contract holes:** The spec says cluster-planner does "Phase 0 — Premise check (lightweight)" and returns STATUS: decision_needed if concerns surface. But SPEC doesn't define what "concerns surface" means operationally. How does a cluster-planner *recognize* that a premise is unsound *before* exploring? What if exploration reveals premise is wrong? Does cluster-planner re-check? Risk: a leaf could write SPEC/PLAN/TASKS on a malformed premise and return STATUS: ok because it didn't detect the premise was bad until Phase 4 (too late).
./z-harness/plans/plan-decompose/archive/plan-decompose-v1/transcripts/001-gemini-plan-review.prompt.md:34:6. **Ack-gate and partial trees:** SPEC says "If `overlap_count: 0`, SHARED-CONCERNS.md is still written (for audit/log consistency) but ack-gate auto-passes." And "/z-implement-all discovery refuses to start the tree if `SHARED-CONCERNS.md` exists with `acknowledged: false`." But what if only 1 of 3 clusters completed? Is SHARED-CONCERNS.md written for the 2 completed clusters only? Or do we wait for all? PLAN says "If ≥1 cluster succeeds, proceed to Phase 4 — partial trees are valid." So partial trees should still get reconciliation. But reconciliation on incomplete data: what if the 3rd cluster (never started) would have touched the same files? Risk: ack-gate is based on stale overlap data. Recommend: SHARED-CONCERNS.md mark `partial: true` if not all clusters finished, and warn user that re-running cluster 3 later might update overlaps.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/findings.md:30:- [codex] **No spec guidance for malformed cluster TASKS.md during Phase 4 validation.** SPEC says "parse each cluster's TASKS.md" but doesn't say what happens on YAML/format errors. Reasonable interpretation: mark cluster failed with `cluster_files_inconsistent` and continue.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/findings.md:55:- Malformed TASKS.md handling in Phase 4
./research/hermes-agent/skills/software-development/systematic-debugging/SKILL.md:210:- Did it work? → Phase 4
./research/hermes-agent/skills/software-development/systematic-debugging/SKILL.md:223:## Phase 4: Implementation
./research/hermes-agent/skills/software-development/systematic-debugging/SKILL.md:294:**If 3+ fixes failed:** Question the architecture (Phase 4 step 5).
./research/hermes-agent/skills/software-development/hermes-s6-container-supervision/SKILL.md:22:- Changing the rendered run-script for per-profile gateways (Phase 4)
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:16:+You do not call Codex/Gemini consultants (cost discipline — no per-leaf consult in v1). You do not call `Explore` (cost discipline — too expensive for narrow scopes). You DO call `doc-fetcher` iff `docs/llm/INDEX.json` exists in the repo. You DO call `complexity-classifier` in Phase 5.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:37:+  If `RESOLVED_DECISION:` is present, **skip Phases 0-3** and resume from Phase 4 with the resolution baked in. Append the resolution to `archive/<run-id>/decisions.md` under a "Resolved late" section before writing SPEC/PLAN.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:79:+No ancestor is carved out. At dispatch time `/z-plan-split` Phase 5 has not yet written the parent root MANIFEST.md (the root MANIFEST is only written AFTER all cluster-planners return), so any MANIFEST.md visible to this guard indicates the real anti-nesting case: a cluster being planted inside an existing tree (manual nested invocation or a stale prior run). Refuse on the first one found.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:108:+If premise concerns surface, return `STATUS: decision_needed` with a structured payload whose QUESTION is "is this scope coherent?" and AFFECTED_FILES is `[]`. Otherwise write a one-paragraph "premise accepted, here's what I take the goal to be" note into a scratch variable; you will paste it into PLAN.md "Goal" in Phase 4.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:217:+After escalating one decision, **stop**. Do not proceed to Phase 4. The main thread will resolve the decision and re-spawn you with a `RESOLVED_DECISION:` block; on re-spawn, you skip Phases 0-3 and resume at Phase 4.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:223:+## Phase 4 — Write SPEC.md + PLAN.md (compressed format)
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:253:+## Phase 5 — Write TASKS.md (with complexity stamping)
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:265:+  - **Complexity:** <stamped in Phase 5 by complexity-classifier>
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:284:+The `FILES_TOUCHED` return field is derived from the union of every task's `**Files:**` line. Keep them honest — the main thread's reconciliation Phase 4 will re-parse TASKS.md and cross-check against `FILES_TOUCHED`; mismatch → `cluster_files_inconsistent` event and the cluster is marked failed.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:437:+- `ready` — Phase 5 finalized with all clusters ready.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:438:+- `partial` — Phase 5 finalized with ≥1 cluster ready and ≥1 failed.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:445:+- `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:581:+- **`STATUS: ok`** → mark cluster `ready` in the in-memory MANIFEST state with `attempts: 1`. Record `final_status_at: <UTC ISO>`. Stash the returned `FILES_TOUCHED` JSON array for Phase 4 reconciliation.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:609:+…push-notify the user, write a minimal MANIFEST.md (`status: failed`, no SHARED-CONCERNS.md). Then per the Early-exit telemetry contract: emit `phase_end` for Phase 3, followed by `plan_split_run_end` with `status: "total_cluster_failure"`, then exit. Do not proceed to Phase 4.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:611:+If ≥1 cluster is `ready`, proceed to Phase 4 — partial trees are valid.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:615:+## Phase 4 — Reconciliation (file-overlap detection)
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:627:+Re-evaluate the total-failure gate after any newly-failed cluster. If after Phase 4 file-inconsistency checks **all** clusters are failed, halt exactly as Phase 3 would: emit `cluster_failed` events (already done), then `total_cluster_failure`, then `phase_end` for Phase 4, then `plan_split_run_end` with `status: "total_cluster_failure"`, then exit (no SHARED-CONCERNS.md; minimal MANIFEST with `status: failed`).
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:629:+**Re-validation cascade (mandatory after any Phase 4 demotion).** Demoting a previously-ready cluster to `failed` invalidates the overlap index that was built from the full ready set. Before writing any Phase 5 artifact, **rebuild the overlap index from scratch using only the clusters whose status is still `ready` after Phase 4 demotions**:
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:637:+Only after the rebuild may Phase 5 write `SHARED-CONCERNS.md`, populate `overlap_count` / `partial_tree`, and set MANIFEST `status`. Skipping the rebuild would write stale overlap data that references files contributed by a now-failed cluster.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:664:+## Phase 5 — Write SHARED-CONCERNS.md + MANIFEST.md + finalize
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:761:+Emit `phase_end` for Phase 5, then log `plan_split_run_end` with the full payload (per the Early-exit telemetry contract — this is the non-early, success/partial path):
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:769:+where `$STATUS` is `"ready"` (all clusters succeeded) or `"partial"` (≥1 ready and ≥1 failed). The total-failure branch never reaches Phase 5 — it exits in Phase 3 or Phase 4 per the Early-exit telemetry contract.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:880:+- `ready` — Phase 5 finalized with all clusters ready.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:881:+- `partial` — Phase 5 finalized with ≥1 cluster ready and ≥1 failed.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:888:+- `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1024:+- **`STATUS: ok`** → mark cluster `ready` in the in-memory MANIFEST state with `attempts: 1`. Record `final_status_at: <UTC ISO>`. Stash the returned `FILES_TOUCHED` JSON array for Phase 4 reconciliation.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1052:+…push-notify the user, write a minimal MANIFEST.md (`status: failed`, no SHARED-CONCERNS.md). Then per the Early-exit telemetry contract: emit `phase_end` for Phase 3, followed by `plan_split_run_end` with `status: "total_cluster_failure"`, then exit. Do not proceed to Phase 4.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1054:+If ≥1 cluster is `ready`, proceed to Phase 4 — partial trees are valid.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1058:+## Phase 4 — Reconciliation (file-overlap detection)
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1070:+Re-evaluate the total-failure gate after any newly-failed cluster. If after Phase 4 file-inconsistency checks **all** clusters are failed, halt exactly as Phase 3 would: emit `cluster_failed` events (already done), then `total_cluster_failure`, then `phase_end` for Phase 4, then `plan_split_run_end` with `status: "total_cluster_failure"`, then exit (no SHARED-CONCERNS.md; minimal MANIFEST with `status: failed`).
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1072:+**Re-validation cascade (mandatory after any Phase 4 demotion).** Demoting a previously-ready cluster to `failed` invalidates the overlap index that was built from the full ready set. Before writing any Phase 5 artifact, **rebuild the overlap index from scratch using only the clusters whose status is still `ready` after Phase 4 demotions**:
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1080:+Only after the rebuild may Phase 5 write `SHARED-CONCERNS.md`, populate `overlap_count` / `partial_tree`, and set MANIFEST `status`. Skipping the rebuild would write stale overlap data that references files contributed by a now-failed cluster.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1107:+## Phase 5 — Write SHARED-CONCERNS.md + MANIFEST.md + finalize
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1204:+Emit `phase_end` for Phase 5, then log `plan_split_run_end` with the full payload (per the Early-exit telemetry contract — this is the non-early, success/partial path):
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1212:+where `$STATUS` is `"ready"` (all clusters succeeded) or `"partial"` (≥1 ready and ≥1 failed). The total-failure branch never reaches Phase 5 — it exits in Phase 3 or Phase 4 per the Early-exit telemetry contract.
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1545:+| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1568:+| `cluster_files_inconsistent` | `/z-plan-split` Phase 4 when `FILES_TOUCHED` ↔ TASKS.md disagree |
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1569:+| `total_cluster_failure` | `/z-plan-split` Phase 3 or Phase 4 when every cluster ends `failed` |
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1570:+| `overlap_detected` | `/z-plan-split` Phase 4 (per overlapping path) |
./z-harness/plans/plan-decompose/archive/20260523T053503Z-review/cumulative.diff:1571:+| `overlap_index_rebuilt` | `/z-plan-split` Phase 4 after any post-Phase-3 cluster demotion |
./z-harness/plans/plan-decompose/archive/tasks/T001/review-v2.response.md:76:++No ancestor is carved out. At dispatch time `/z-plan-split` Phase 5 has not yet written the parent root MANIFEST.md (the root MANIFEST is only written AFTER all cluster-planners return), so any MANIFEST.md visible to this guard indicates the real anti-nesting case: a cluster being planted inside an existing tree (manual nested invocation or a stale prior run). Refuse on the first one found.
./z-harness/plans/plan-decompose/archive/tasks/T001/review.prompt.md:21:### Phase 4 — Write SPEC.md + PLAN.md
./z-harness/plans/plan-decompose/archive/tasks/T001/review.prompt.md:24:### Phase 5 — Write TASKS.md
./z-harness/plans/plan-decompose/archive/tasks/T001/review.prompt.md:35:- Re-spawn semantics: on RESOLVED_DECISION: block in prompt, resume from Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T001/review.prompt.md:58:+You do not call Codex/Gemini consultants (cost discipline — no per-leaf consult in v1). You do not call `Explore` (cost discipline — too expensive for narrow scopes). You DO call `doc-fetcher` iff `docs/llm/INDEX.json` exists in the repo. You DO call `complexity-classifier` in Phase 5.
./z-harness/plans/plan-decompose/archive/tasks/T001/review.prompt.md:79:+  If `RESOLVED_DECISION:` is present, **skip Phases 0-3** and resume from Phase 4 with the resolution baked in. Append the resolution to `archive/<run-id>/decisions.md` under a "Resolved late" section before writing SPEC/PLAN.
./z-harness/plans/plan-decompose/archive/tasks/T001/review.prompt.md:146:+If premise concerns surface, return `STATUS: decision_needed` with a structured payload whose QUESTION is "is this scope coherent?" and AFFECTED_FILES is `[]`. Otherwise write a one-paragraph "premise accepted, here's what I take the goal to be" note into a scratch variable; you will paste it into PLAN.md "Goal" in Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T001/review.prompt.md:255:+After escalating one decision, **stop**. Do not proceed to Phase 4. The main thread will resolve the decision and re-spawn you with a `RESOLVED_DECISION:` block; on re-spawn, you skip Phases 0-3 and resume at Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T001/review.prompt.md:261:+## Phase 4 — Write SPEC.md + PLAN.md (compressed format)
./z-harness/plans/plan-decompose/archive/tasks/T001/review.prompt.md:291:+## Phase 5 — Write TASKS.md (with complexity stamping)
./z-harness/plans/plan-decompose/archive/tasks/T001/review.prompt.md:303:+  - **Complexity:** <stamped in Phase 5 by complexity-classifier>
./z-harness/plans/plan-decompose/archive/tasks/T001/review.prompt.md:322:+The `FILES_TOUCHED` return field is derived from the union of every task's `**Files:**` line. Keep them honest — the main thread's reconciliation Phase 4 will re-parse TASKS.md and cross-check against `FILES_TOUCHED`; mismatch → `cluster_files_inconsistent` event and the cluster is marked failed.
./z-harness/plans/plan-decompose/archive/tasks/T001/diff-v1.patch:16:+You do not call Codex/Gemini consultants (cost discipline — no per-leaf consult in v1). You do not call `Explore` (cost discipline — too expensive for narrow scopes). You DO call `doc-fetcher` iff `docs/llm/INDEX.json` exists in the repo. You DO call `complexity-classifier` in Phase 5.
./z-harness/plans/plan-decompose/archive/tasks/T001/diff-v1.patch:37:+  If `RESOLVED_DECISION:` is present, **skip Phases 0-3** and resume from Phase 4 with the resolution baked in. Append the resolution to `archive/<run-id>/decisions.md` under a "Resolved late" section before writing SPEC/PLAN.
./z-harness/plans/plan-decompose/archive/tasks/T001/diff-v1.patch:104:+If premise concerns surface, return `STATUS: decision_needed` with a structured payload whose QUESTION is "is this scope coherent?" and AFFECTED_FILES is `[]`. Otherwise write a one-paragraph "premise accepted, here's what I take the goal to be" note into a scratch variable; you will paste it into PLAN.md "Goal" in Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T001/diff-v1.patch:213:+After escalating one decision, **stop**. Do not proceed to Phase 4. The main thread will resolve the decision and re-spawn you with a `RESOLVED_DECISION:` block; on re-spawn, you skip Phases 0-3 and resume at Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T001/diff-v1.patch:219:+## Phase 4 — Write SPEC.md + PLAN.md (compressed format)
./z-harness/plans/plan-decompose/archive/tasks/T001/diff-v1.patch:249:+## Phase 5 — Write TASKS.md (with complexity stamping)
./z-harness/plans/plan-decompose/archive/tasks/T001/diff-v1.patch:261:+  - **Complexity:** <stamped in Phase 5 by complexity-classifier>
./z-harness/plans/plan-decompose/archive/tasks/T001/diff-v1.patch:280:+The `FILES_TOUCHED` return field is derived from the union of every task's `**Files:**` line. Keep them honest — the main thread's reconciliation Phase 4 will re-parse TASKS.md and cross-check against `FILES_TOUCHED`; mismatch → `cluster_files_inconsistent` event and the cluster is marked failed.
./z-harness/plans/plan-decompose/archive/tasks/T001/delta-v2.patch:54:++No ancestor is carved out. At dispatch time `/z-plan-split` Phase 5 has not yet written the parent root MANIFEST.md (the root MANIFEST is only written AFTER all cluster-planners return), so any MANIFEST.md visible to this guard indicates the real anti-nesting case: a cluster being planted inside an existing tree (manual nested invocation or a stale prior run). Refuse on the first one found.
./z-harness/plans/plan-decompose/archive/tasks/T001/review.response.md:36:### Phase 4 — Write SPEC.md + PLAN.md
./z-harness/plans/plan-decompose/archive/tasks/T001/review.response.md:39:### Phase 5 — Write TASKS.md
./z-harness/plans/plan-decompose/archive/tasks/T001/review.response.md:50:- Re-spawn semantics: on RESOLVED_DECISION: block in prompt, resume from Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T001/review.response.md:73:+You do not call Codex/Gemini consultants (cost discipline — no per-leaf consult in v1). You do not call `Explore` (cost discipline — too expensive for narrow scopes). You DO call `doc-fetcher` iff `docs/llm/INDEX.json` exists in the repo. You DO call `complexity-classifier` in Phase 5.
./z-harness/plans/plan-decompose/archive/tasks/T001/review.response.md:94:+  If `RESOLVED_DECISION:` is present, **skip Phases 0-3** and resume from Phase 4 with the resolution baked in. Append the resolution to `archive/<run-id>/decisions.md` under a "Resolved late" section before writing SPEC/PLAN.
./z-harness/plans/plan-decompose/archive/tasks/T001/review.response.md:161:+If premise concerns surface, return `STATUS: decision_needed` with a structured payload whose QUESTION is "is this scope coherent?" and AFFECTED_FILES is `[]`. Otherwise write a one-paragraph "premise accepted, here's what I take the goal to be" note into a scratch variable; you will paste it into PLAN.md "Goal" in Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T001/review.response.md:270:+After escalating one decision, **stop**. Do not proceed to Phase 4. The main thread will resolve the decision and re-spawn you with a `RESOLVED_DECISION:` block; on re-spawn, you skip Phases 0-3 and resume at Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T001/review.response.md:276:+## Phase 4 — Write SPEC.md + PLAN.md (compressed format)
./z-harness/plans/plan-decompose/archive/tasks/T001/review.response.md:306:+## Phase 5 — Write TASKS.md (with complexity stamping)
./z-harness/plans/plan-decompose/archive/tasks/T001/review.response.md:318:+  - **Complexity:** <stamped in Phase 5 by complexity-classifier>
./z-harness/plans/plan-decompose/archive/tasks/T001/review.response.md:337:+The `FILES_TOUCHED` return field is derived from the union of every task's `**Files:**` line. Keep them honest — the main thread's reconciliation Phase 4 will re-parse TASKS.md and cross-check against `FILES_TOUCHED`; mismatch → `cluster_files_inconsistent` event and the cluster is marked failed.
./z-harness/plans/plan-decompose/archive/tasks/T001/diff.patch:16:+You do not call Codex/Gemini consultants (cost discipline — no per-leaf consult in v1). You do not call `Explore` (cost discipline — too expensive for narrow scopes). You DO call `doc-fetcher` iff `docs/llm/INDEX.json` exists in the repo. You DO call `complexity-classifier` in Phase 5.
./z-harness/plans/plan-decompose/archive/tasks/T001/diff.patch:37:+  If `RESOLVED_DECISION:` is present, **skip Phases 0-3** and resume from Phase 4 with the resolution baked in. Append the resolution to `archive/<run-id>/decisions.md` under a "Resolved late" section before writing SPEC/PLAN.
./z-harness/plans/plan-decompose/archive/tasks/T001/diff.patch:79:+No ancestor is carved out. At dispatch time `/z-plan-split` Phase 5 has not yet written the parent root MANIFEST.md (the root MANIFEST is only written AFTER all cluster-planners return), so any MANIFEST.md visible to this guard indicates the real anti-nesting case: a cluster being planted inside an existing tree (manual nested invocation or a stale prior run). Refuse on the first one found.
./z-harness/plans/plan-decompose/archive/tasks/T001/diff.patch:108:+If premise concerns surface, return `STATUS: decision_needed` with a structured payload whose QUESTION is "is this scope coherent?" and AFFECTED_FILES is `[]`. Otherwise write a one-paragraph "premise accepted, here's what I take the goal to be" note into a scratch variable; you will paste it into PLAN.md "Goal" in Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T001/diff.patch:217:+After escalating one decision, **stop**. Do not proceed to Phase 4. The main thread will resolve the decision and re-spawn you with a `RESOLVED_DECISION:` block; on re-spawn, you skip Phases 0-3 and resume at Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T001/diff.patch:223:+## Phase 4 — Write SPEC.md + PLAN.md (compressed format)
./z-harness/plans/plan-decompose/archive/tasks/T001/diff.patch:253:+## Phase 5 — Write TASKS.md (with complexity stamping)
./z-harness/plans/plan-decompose/archive/tasks/T001/diff.patch:265:+  - **Complexity:** <stamped in Phase 5 by complexity-classifier>
./z-harness/plans/plan-decompose/archive/tasks/T001/diff.patch:284:+The `FILES_TOUCHED` return field is derived from the union of every task's `**Files:**` line. Keep them honest — the main thread's reconciliation Phase 4 will re-parse TASKS.md and cross-check against `FILES_TOUCHED`; mismatch → `cluster_files_inconsistent` event and the cluster is marked failed.
./z-harness/plans/plan-decompose/archive/tasks/T004/diff.patch:74:+| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
./z-harness/plans/plan-decompose/archive/tasks/T004/diff.patch:97:+| `cluster_files_inconsistent` | `/z-plan-split` Phase 4 when `FILES_TOUCHED` ↔ TASKS.md disagree |
./z-harness/plans/plan-decompose/archive/tasks/T004/diff.patch:98:+| `total_cluster_failure` | `/z-plan-split` Phase 3 or Phase 4 when every cluster ends `failed` |
./z-harness/plans/plan-decompose/archive/tasks/T004/diff.patch:99:+| `overlap_detected` | `/z-plan-split` Phase 4 (per overlapping path) |
./z-harness/plans/plan-decompose/archive/tasks/T004/diff.patch:100:+| `overlap_index_rebuilt` | `/z-plan-split` Phase 4 after any post-Phase-3 cluster demotion |
./research/hermes-agent/plugins/hermes-achievements/docs/achievements-performance-implementation-plan.md:98:## Phase 4 — Incremental Scanning (optional but recommended)
./z-harness/plans/plan-decompose/archive/tasks/T002/review.prompt.md:8:- Phase 4: TASKS.md Files: lines canonical; validate against FILES_TOUCHED → cluster_files_inconsistent on mismatch; path normalization (strip leading / or ./, collapse ./.., normalize separator, reject escapes); cascading severity high > medium > low; files touched by 1 cluster excluded.
./z-harness/plans/plan-decompose/archive/tasks/T002/review.prompt.md:9:- Phase 5: SHARED-CONCERNS.md frontmatter (acknowledged:false unless overlap_count:0, partial_tree); MANIFEST.md with cluster table, run-order, attempts; plan_split_run_end with {total_clusters,clusters_ready,clusters_failed,overlap_count,partial_tree}; push-notify.
./z-harness/plans/plan-decompose/archive/tasks/T002/review.prompt.md:204:+- **`STATUS: ok`** → mark cluster `ready` in the in-memory MANIFEST state with `attempts: 1`. Record `final_status_at: <UTC ISO>`. Stash the returned `FILES_TOUCHED` JSON array for Phase 4 reconciliation.
./z-harness/plans/plan-decompose/archive/tasks/T002/review.prompt.md:232:+…push-notify the user, write a minimal MANIFEST.md (`status: failed`, no SHARED-CONCERNS.md), and exit. Do not proceed to Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T002/review.prompt.md:234:+If ≥1 cluster is `ready`, proceed to Phase 4 — partial trees are valid.
./z-harness/plans/plan-decompose/archive/tasks/T002/review.prompt.md:238:+## Phase 4 — Reconciliation (file-overlap detection)
./z-harness/plans/plan-decompose/archive/tasks/T002/review.prompt.md:277:+## Phase 5 — Write SHARED-CONCERNS.md + MANIFEST.md + finalize
./z-harness/plans/plan-decompose/archive/tasks/T002/review.prompt.md:592:+- **`STATUS: ok`** → mark cluster `ready` in the in-memory MANIFEST state with `attempts: 1`. Record `final_status_at: <UTC ISO>`. Stash the returned `FILES_TOUCHED` JSON array for Phase 4 reconciliation.
./z-harness/plans/plan-decompose/archive/tasks/T002/review.prompt.md:620:+…push-notify the user, write a minimal MANIFEST.md (`status: failed`, no SHARED-CONCERNS.md), and exit. Do not proceed to Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T002/review.prompt.md:622:+If ≥1 cluster is `ready`, proceed to Phase 4 — partial trees are valid.
./z-harness/plans/plan-decompose/archive/tasks/T002/review.prompt.md:626:+## Phase 4 — Reconciliation (file-overlap detection)
./z-harness/plans/plan-decompose/archive/tasks/T002/review.prompt.md:665:+## Phase 5 — Write SHARED-CONCERNS.md + MANIFEST.md + finalize
./z-harness/plans/plan-decompose/archive/tasks/T002/diff-v1.patch:185:+- **`STATUS: ok`** → mark cluster `ready` in the in-memory MANIFEST state with `attempts: 1`. Record `final_status_at: <UTC ISO>`. Stash the returned `FILES_TOUCHED` JSON array for Phase 4 reconciliation.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff-v1.patch:213:+…push-notify the user, write a minimal MANIFEST.md (`status: failed`, no SHARED-CONCERNS.md), and exit. Do not proceed to Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff-v1.patch:215:+If ≥1 cluster is `ready`, proceed to Phase 4 — partial trees are valid.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff-v1.patch:219:+## Phase 4 — Reconciliation (file-overlap detection)
./z-harness/plans/plan-decompose/archive/tasks/T002/diff-v1.patch:258:+## Phase 5 — Write SHARED-CONCERNS.md + MANIFEST.md + finalize
./z-harness/plans/plan-decompose/archive/tasks/T002/diff-v1.patch:573:+- **`STATUS: ok`** → mark cluster `ready` in the in-memory MANIFEST state with `attempts: 1`. Record `final_status_at: <UTC ISO>`. Stash the returned `FILES_TOUCHED` JSON array for Phase 4 reconciliation.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff-v1.patch:601:+…push-notify the user, write a minimal MANIFEST.md (`status: failed`, no SHARED-CONCERNS.md), and exit. Do not proceed to Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff-v1.patch:603:+If ≥1 cluster is `ready`, proceed to Phase 4 — partial trees are valid.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff-v1.patch:607:+## Phase 4 — Reconciliation (file-overlap detection)
./z-harness/plans/plan-decompose/archive/tasks/T002/diff-v1.patch:646:+## Phase 5 — Write SHARED-CONCERNS.md + MANIFEST.md + finalize
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:78:++- `ready` — Phase 5 finalized with all clusters ready.
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:79:++- `partial` — Phase 5 finalized with ≥1 cluster ready and ≥1 failed.
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:86:++- `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:126:-+…push-notify the user, write a minimal MANIFEST.md (`status: failed`, no SHARED-CONCERNS.md), and exit. Do not proceed to Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:127:++…push-notify the user, write a minimal MANIFEST.md (`status: failed`, no SHARED-CONCERNS.md). Then per the Early-exit telemetry contract: emit `phase_end` for Phase 3, followed by `plan_split_run_end` with `status: "total_cluster_failure"`, then exit. Do not proceed to Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:129: +If ≥1 cluster is `ready`, proceed to Phase 4 — partial trees are valid.
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:136:++Re-evaluate the total-failure gate after any newly-failed cluster. If after Phase 4 file-inconsistency checks **all** clusters are failed, halt exactly as Phase 3 would: emit `cluster_failed` events (already done), then `total_cluster_failure`, then `phase_end` for Phase 4, then `plan_split_run_end` with `status: "total_cluster_failure"`, then exit (no SHARED-CONCERNS.md; minimal MANIFEST with `status: failed`).
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:138:++**Re-validation cascade (mandatory after any Phase 4 demotion).** Demoting a previously-ready cluster to `failed` invalidates the overlap index that was built from the full ready set. Before writing any Phase 5 artifact, **rebuild the overlap index from scratch using only the clusters whose status is still `ready` after Phase 4 demotions**:
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:146:++Only after the rebuild may Phase 5 write `SHARED-CONCERNS.md`, populate `overlap_count` / `partial_tree`, and set MANIFEST `status`. Skipping the rebuild would write stale overlap data that references files contributed by a now-failed cluster.
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:182:++Emit `phase_end` for Phase 5, then log `plan_split_run_end` with the full payload (per the Early-exit telemetry contract — this is the non-early, success/partial path):
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:192:++where `$STATUS` is `"ready"` (all clusters succeeded) or `"partial"` (≥1 ready and ≥1 failed). The total-failure branch never reaches Phase 5 — it exits in Phase 3 or Phase 4 per the Early-exit telemetry contract.
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:273:++- `ready` — Phase 5 finalized with all clusters ready.
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:274:++- `partial` — Phase 5 finalized with ≥1 cluster ready and ≥1 failed.
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:281:++- `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:321:-+…push-notify the user, write a minimal MANIFEST.md (`status: failed`, no SHARED-CONCERNS.md), and exit. Do not proceed to Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:322:++…push-notify the user, write a minimal MANIFEST.md (`status: failed`, no SHARED-CONCERNS.md). Then per the Early-exit telemetry contract: emit `phase_end` for Phase 3, followed by `plan_split_run_end` with `status: "total_cluster_failure"`, then exit. Do not proceed to Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:324: +If ≥1 cluster is `ready`, proceed to Phase 4 — partial trees are valid.
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:331:++Re-evaluate the total-failure gate after any newly-failed cluster. If after Phase 4 file-inconsistency checks **all** clusters are failed, halt exactly as Phase 3 would: emit `cluster_failed` events (already done), then `total_cluster_failure`, then `phase_end` for Phase 4, then `plan_split_run_end` with `status: "total_cluster_failure"`, then exit (no SHARED-CONCERNS.md; minimal MANIFEST with `status: failed`).
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:333:++**Re-validation cascade (mandatory after any Phase 4 demotion).** Demoting a previously-ready cluster to `failed` invalidates the overlap index that was built from the full ready set. Before writing any Phase 5 artifact, **rebuild the overlap index from scratch using only the clusters whose status is still `ready` after Phase 4 demotions**:
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:341:++Only after the rebuild may Phase 5 write `SHARED-CONCERNS.md`, populate `overlap_count` / `partial_tree`, and set MANIFEST `status`. Skipping the rebuild would write stale overlap data that references files contributed by a now-failed cluster.
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:377:++Emit `phase_end` for Phase 5, then log `plan_split_run_end` with the full payload (per the Early-exit telemetry contract — this is the non-early, success/partial path):
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:387:++where `$STATUS` is `"ready"` (all clusters succeeded) or `"partial"` (≥1 ready and ≥1 failed). The total-failure branch never reaches Phase 5 — it exits in Phase 3 or Phase 4 per the Early-exit telemetry contract.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:82:+- `ready` — Phase 5 finalized with all clusters ready.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:83:+- `partial` — Phase 5 finalized with ≥1 cluster ready and ≥1 failed.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:90:+- `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:226:+- **`STATUS: ok`** → mark cluster `ready` in the in-memory MANIFEST state with `attempts: 1`. Record `final_status_at: <UTC ISO>`. Stash the returned `FILES_TOUCHED` JSON array for Phase 4 reconciliation.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:254:+…push-notify the user, write a minimal MANIFEST.md (`status: failed`, no SHARED-CONCERNS.md). Then per the Early-exit telemetry contract: emit `phase_end` for Phase 3, followed by `plan_split_run_end` with `status: "total_cluster_failure"`, then exit. Do not proceed to Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:256:+If ≥1 cluster is `ready`, proceed to Phase 4 — partial trees are valid.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:260:+## Phase 4 — Reconciliation (file-overlap detection)
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:272:+Re-evaluate the total-failure gate after any newly-failed cluster. If after Phase 4 file-inconsistency checks **all** clusters are failed, halt exactly as Phase 3 would: emit `cluster_failed` events (already done), then `total_cluster_failure`, then `phase_end` for Phase 4, then `plan_split_run_end` with `status: "total_cluster_failure"`, then exit (no SHARED-CONCERNS.md; minimal MANIFEST with `status: failed`).
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:274:+**Re-validation cascade (mandatory after any Phase 4 demotion).** Demoting a previously-ready cluster to `failed` invalidates the overlap index that was built from the full ready set. Before writing any Phase 5 artifact, **rebuild the overlap index from scratch using only the clusters whose status is still `ready` after Phase 4 demotions**:
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:282:+Only after the rebuild may Phase 5 write `SHARED-CONCERNS.md`, populate `overlap_count` / `partial_tree`, and set MANIFEST `status`. Skipping the rebuild would write stale overlap data that references files contributed by a now-failed cluster.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:309:+## Phase 5 — Write SHARED-CONCERNS.md + MANIFEST.md + finalize
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:406:+Emit `phase_end` for Phase 5, then log `plan_split_run_end` with the full payload (per the Early-exit telemetry contract — this is the non-early, success/partial path):
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:414:+where `$STATUS` is `"ready"` (all clusters succeeded) or `"partial"` (≥1 ready and ≥1 failed). The total-failure branch never reaches Phase 5 — it exits in Phase 3 or Phase 4 per the Early-exit telemetry contract.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:525:+- `ready` — Phase 5 finalized with all clusters ready.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:526:+- `partial` — Phase 5 finalized with ≥1 cluster ready and ≥1 failed.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:533:+- `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:669:+- **`STATUS: ok`** → mark cluster `ready` in the in-memory MANIFEST state with `attempts: 1`. Record `final_status_at: <UTC ISO>`. Stash the returned `FILES_TOUCHED` JSON array for Phase 4 reconciliation.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:697:+…push-notify the user, write a minimal MANIFEST.md (`status: failed`, no SHARED-CONCERNS.md). Then per the Early-exit telemetry contract: emit `phase_end` for Phase 3, followed by `plan_split_run_end` with `status: "total_cluster_failure"`, then exit. Do not proceed to Phase 4.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:699:+If ≥1 cluster is `ready`, proceed to Phase 4 — partial trees are valid.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:703:+## Phase 4 — Reconciliation (file-overlap detection)
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:715:+Re-evaluate the total-failure gate after any newly-failed cluster. If after Phase 4 file-inconsistency checks **all** clusters are failed, halt exactly as Phase 3 would: emit `cluster_failed` events (already done), then `total_cluster_failure`, then `phase_end` for Phase 4, then `plan_split_run_end` with `status: "total_cluster_failure"`, then exit (no SHARED-CONCERNS.md; minimal MANIFEST with `status: failed`).
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:717:+**Re-validation cascade (mandatory after any Phase 4 demotion).** Demoting a previously-ready cluster to `failed` invalidates the overlap index that was built from the full ready set. Before writing any Phase 5 artifact, **rebuild the overlap index from scratch using only the clusters whose status is still `ready` after Phase 4 demotions**:
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:725:+Only after the rebuild may Phase 5 write `SHARED-CONCERNS.md`, populate `overlap_count` / `partial_tree`, and set MANIFEST `status`. Skipping the rebuild would write stale overlap data that references files contributed by a now-failed cluster.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:752:+## Phase 5 — Write SHARED-CONCERNS.md + MANIFEST.md + finalize
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:849:+Emit `phase_end` for Phase 5, then log `plan_split_run_end` with the full payload (per the Early-exit telemetry contract — this is the non-early, success/partial path):
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:857:+where `$STATUS` is `"ready"` (all clusters succeeded) or `"partial"` (≥1 ready and ≥1 failed). The total-failure branch never reaches Phase 5 — it exits in Phase 3 or Phase 4 per the Early-exit telemetry contract.
./z-harness/plans/plan-decompose/archive/20260522T000000Z-plan-decompose/transcripts/002-gemini-bundled-decisions.prompt.md:19:- Phase 4 finalizes
./z-harness/plans/plan-decompose/archive/20260522T000000Z-plan-decompose/transcripts/002-gemini-bundled-decisions.prompt.md:91:Keep each recommendation to 2–4 sentences of reasoning. This is input to the main thread's Phase 5 (present + approve) — the user will see your picks alongside existing tentative leans.
./z-harness/plans/compaction-cadence/SPEC.md:71:**Add:** a new step between Phase 3.5 (test run) and Phase 4 (consultant spawn) — "Phase 3.7 — pre-consult compaction breakpoint":
./z-harness/plans/compaction-cadence/SPEC.md:76:  - **(b) Proceed now** — continue into Phase 4. **Only on this choice** write the state file (see below).
./z-harness/plans/compaction-cadence/SPEC.md:91:2. If `head_sha` matches `git rev-parse HEAD` AND the referenced `cumulative_diff_path` file still exists, **fast-forward**: skip Phase 0–3.5, reuse the existing diff and test results, enter Phase 4 directly. Log a `review_resume_fast_forward` event.
./z-harness/plans/compaction-cadence/SPEC.md:98:- Proceed + run interrupted before Phase 4 completes + re-invoked with HEAD unchanged: fast-forward to Phase 4.
./z-harness/plans/compaction-cadence/TASKS.md:91:- `agents/mr-reviewer.md` (only if it owns the Phase 4 spawn; otherwise skip)
./z-harness/plans/compaction-cadence/TASKS.md:96:- New "Phase 3.7 — pre-consult compaction breakpoint" between current Phase 3.5 and Phase 4.
./z-harness/plans/compaction-cadence/TASKS.md:100:  1. State file + HEAD matches + diff file present → fast-forward to Phase 4, emit `review_resume_fast_forward`.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/decisions.md:28:  - (a) **Yes — before Phase 4 consultant spawn** (the heaviest single context burn in the whole harness).
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/decisions.md:30:- **Tentative:** (a). Phase 4 reads the cumulative diff + SPEC + PLAN + TASKS + concept docs and hands them to two consultants — exactly the hot spot identified in Phase 1. A pre-Phase-4 push notification ("about to spawn consultants; `/compact` first if context is heavy, then continue") costs nothing if user dismisses.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/SPEC.md:71:**Add:** a new step between Phase 3.5 (test run) and Phase 4 (consultant spawn) — "Phase 3.7 — pre-consult compaction breakpoint":
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/SPEC.md:76:  - **(b) Proceed now** — continue into Phase 4. **Only on this choice** write the state file (see below).
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/SPEC.md:91:2. If `head_sha` matches `git rev-parse HEAD` AND the referenced `cumulative_diff_path` file still exists, **fast-forward**: skip Phase 0–3.5, reuse the existing diff and test results, enter Phase 4 directly. Log a `review_resume_fast_forward` event.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/SPEC.md:98:- Proceed + run interrupted before Phase 4 completes + re-invoked with HEAD unchanged: fast-forward to Phase 4.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/phase3-decisions-final.md:22:**Rule:** Before spawning the cumulative-diff consultants in Phase 4, emit a push notification: *"About to spawn consultants on cumulative diff (heaviest context burn). Recommended: `/clear`, then re-invoke `/z-review-all` to continue from this point. Dismiss to proceed now."*
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/TASKS.md:87:- `agents/mr-reviewer.md` (only if it owns the Phase 4 spawn; otherwise skip)
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/TASKS.md:92:- New "Phase 3.7 — pre-consult compaction breakpoint" between current Phase 3.5 and Phase 4.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/TASKS.md:96:  1. State file + HEAD matches + diff file present → fast-forward to Phase 4, emit `review_resume_fast_forward`.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/phase1-context.md:9:| `/z-review-all` | one-shot Phase 4 consultant spawn | none | before Phase 3.5 test run; before Phase 4 consultants |
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/phase1-context.md:15:- `commands/z-review-all.md:49–142` — Phase 4 consultant dispatch (no pause)
./z-harness/plans/compaction-cadence/archive/tasks/T006/diff.patch:49: ## Phase 5 — Finalize
./z-harness/plans/compaction-cadence/archive/tasks/T006/diff.patch:114: ## Phase 5 — Finalize
./research/hermes-agent/skills/research/research-paper-writing/SKILL.md:33:│  Phase 2: Experiment     Phase 5: Paper Drafting ◄──┐      │
./research/hermes-agent/skills/research/research-paper-writing/SKILL.md:41:│  Phase 4: Analysis ─────► (feeds back to Phase 2 or 5)     │
./research/hermes-agent/skills/research/research-paper-writing/SKILL.md:559:## Phase 4: Result Analysis
./research/hermes-agent/skills/research/research-paper-writing/SKILL.md:656:| Core claims supported, results significant | Move to Phase 5 (writing) |
./research/hermes-agent/skills/research/research-paper-writing/SKILL.md:659:| Missing one ablation reviewers will ask for | Run it, then Phase 5 |
./research/hermes-agent/skills/research/research-paper-writing/SKILL.md:660:| All experiments done but some failed | Note failures, move to Phase 5 |
./research/hermes-agent/skills/research/research-paper-writing/SKILL.md:778:## Phase 5: Paper Drafting
./research/hermes-agent/skills/research/research-paper-writing/SKILL.md:2128:| **subagent-driven-development** | Phase 5 (Drafting): parallel section writing with 2-stage review (spec compliance then quality) | `skill_view("subagent-driven-development")` |
./research/hermes-agent/skills/research/research-paper-writing/SKILL.md:2131:| **diagramming** | Phase 4-5: creating Excalidraw-based figures and architecture diagrams | `skill_view("diagramming")` |
./research/hermes-agent/skills/research/research-paper-writing/SKILL.md:2132:| **data-science** | Phase 4 (Analysis): Jupyter live kernel for interactive analysis and visualization | `skill_view("data-science")` |
./research/hermes-agent/skills/research/research-paper-writing/SKILL.md:2204:  Status: Phase 5 — drafting Methods section.")
./research/hermes-agent/skills/research/research-paper-writing/SKILL.md:2342:| Results are negative/null | See Phase 4.3 on handling negative results. Consider workshops, TMLR, or reframing as analysis. |
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.prompt.md:7:2. If `head_sha` matches `git rev-parse HEAD` AND the referenced `cumulative_diff_path` file still exists, **fast-forward**: skip Phase 0–3.5, reuse the existing diff and test results, enter Phase 4 directly. Log a `review_resume_fast_forward` event.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.prompt.md:15:  - **(b) Proceed now** — continue into Phase 4. **Only on this choice** write the state file.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.prompt.md:29:- New "Phase 3.7 — pre-consult compaction breakpoint" between Phase 3.5 and Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.prompt.md:33:  1. State file + HEAD matches + diff file present → fast-forward to Phase 4, emit review_resume_fast_forward.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.prompt.md:73:+     - Skip Phases 0–3.5. Restore `BASE_REF` from the state file's `base_ref`. Restore `cumulative.diff` path from `cumulative_diff_path`. Jump directly to Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.prompt.md:86:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.prompt.md:98:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.prompt.md:102:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.prompt.md:120:+- Continue to Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.prompt.md:122: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.prompt.md:126:... (continuing with the rest of the diff covering Phase 5-6 and hard rules changes) ...
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.prompt.md:132:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff-v1.patch:33:+     - Skip Phases 0–3.5. Restore `BASE_REF` from the state file's `base_ref`. Restore `cumulative.diff` path from `cumulative_diff_path`. Jump directly to Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff-v1.patch:47:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff-v1.patch:59:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff-v1.patch:63:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff-v1.patch:81:+- Continue to Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff-v1.patch:83: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff-v1.patch:116: ## Phase 5 — Aggregate findings
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff-v1.patch:213:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff-v1.patch:261:+     - Skip Phases 0–3.5. Restore `BASE_REF` from the state file's `base_ref`. Restore `cumulative.diff` path from `cumulative_diff_path`. Jump directly to Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff-v1.patch:275:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff-v1.patch:287:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff-v1.patch:291:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff-v1.patch:309:+- Continue to Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff-v1.patch:311: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff-v1.patch:316: ## Phase 5 — Aggregate findings
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff-v1.patch:425:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:22:2. If `head_sha` matches `git rev-parse HEAD` AND the referenced `cumulative_diff_path` file still exists, **fast-forward**: skip Phase 0–3.5, reuse the existing diff and test results, enter Phase 4 directly. Log a `review_resume_fast_forward` event.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:30:  - **(b) Proceed now** — continue into Phase 4. **Only on this choice** write the state file.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:44:- New "Phase 3.7 — pre-consult compaction breakpoint" between Phase 3.5 and Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:48:  1. State file + HEAD matches + diff file present → fast-forward to Phase 4, emit review_resume_fast_forward.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:88:+     - Skip Phases 0–3.5. Restore `BASE_REF` from the state file's `base_ref`. Restore `cumulative.diff` path from `cumulative_diff_path`. Jump directly to Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:101:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:113:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:117:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:135:+- Continue to Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:137: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:141:... (continuing with the rest of the diff covering Phase 5-6 and hard rules changes) ...
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:147:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:198:    32	     - Skip Phases 0–3.5. Restore `BASE_REF` from the state file's `base_ref`. Restore `cumulative.diff` path from `cumulative_diff_path`. Jump directly to Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:290:   124	**Any failure here is a blocker.** Surface the failing log slice to the user before proceeding to Phase 4. Treat the same way as a Prong-A finding of severity `blocker` — `/z-review-all` cannot accept a plan whose own tests are broken.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:296:   130	**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:308:   142	> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:312:   146	> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:330:   164	- Continue to Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:332:   166	## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:407:   238	## Phase 5 — Aggregate findings
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:528:   359	This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:577:   The resume path says to restore only `BASE_REF` and the cumulative diff path, then jump to Phase 4. But Phase 4 and later still reference `$BASE`, `$RRUN`, `$Z_HARNESS_SLUG`, `$Z_HARNESS_PLAN_DIR`, `$BASE/archive/$RRUN/cumulative.diff`, and `$BASE/archive/$RRUN/cumulative.stat`. Those are normally initialized in Phase 0 and Phase 3.  
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:578:   Suggested fix: define a concrete fast-forward environment restoration step: set slug, plan dir, `BASE`, `BASE_REF`, `HEAD_SHA`, `RRUN` or `DIFF_PATH`, and `STAT_PATH`; then update Phase 4 to consume those restored paths rather than hard-coded `$BASE/archive/$RRUN/...`.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:582:   The state file stores only `cumulative_diff_path`. Phase 4 also requires `cumulative.stat`, and the spec says to reuse existing diff and test results. There is no path to `cumulative.stat`, no `suite.log`, and no persisted suite status. A fast-forward can silently omit or regenerate assumptions about Phase 3.5.  
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:607:   The spec says “Only on this choice write the state file.” The implementation says if writing fails, log a warning and proceed. That may be pragmatic, but it means an interrupted Phase 4 cannot fast-forward even though the user chose “Proceed now.”  
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:620:   The resume path says to restore only `BASE_REF` and the cumulative diff path, then jump to Phase 4. But Phase 4 and later still reference `$BASE`, `$RRUN`, `$Z_HARNESS_SLUG`, `$Z_HARNESS_PLAN_DIR`, `$BASE/archive/$RRUN/cumulative.diff`, and `$BASE/archive/$RRUN/cumulative.stat`. Those are normally initialized in Phase 0 and Phase 3.  
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:621:   Suggested fix: define a concrete fast-forward environment restoration step: set slug, plan dir, `BASE`, `BASE_REF`, `HEAD_SHA`, `RRUN` or `DIFF_PATH`, and `STAT_PATH`; then update Phase 4 to consume those restored paths rather than hard-coded `$BASE/archive/$RRUN/...`.
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:625:   The state file stores only `cumulative_diff_path`. Phase 4 also requires `cumulative.stat`, and the spec says to reuse existing diff and test results. There is no path to `cumulative.stat`, no `suite.log`, and no persisted suite status. A fast-forward can silently omit or regenerate assumptions about Phase 3.5.  
./z-harness/plans/compaction-cadence/archive/tasks/T005/review.response.md:650:   The spec says “Only on this choice write the state file.” The implementation says if writing fails, log a warning and proceed. That may be pragmatic, but it means an interrupted Phase 4 cannot fast-forward even though the user chose “Proceed now.”  
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff.patch:33:+     - Skip Phases 0–3.5. Restore `BASE_REF` from the state file's `base_ref`. Restore `cumulative.diff` path from `cumulative_diff_path`. Jump directly to Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff.patch:47:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff.patch:59:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff.patch:63:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff.patch:81:+- Continue to Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff.patch:83: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff.patch:116: ## Phase 5 — Aggregate findings
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff.patch:213:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff.patch:261:+     - Skip Phases 0–3.5. Restore `BASE_REF` from the state file's `base_ref`. Restore `cumulative.diff` path from `cumulative_diff_path`. Jump directly to Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff.patch:275:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff.patch:287:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff.patch:291:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff.patch:309:+- Continue to Phase 4.
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff.patch:311: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff.patch:316: ## Phase 5 — Aggregate findings
./z-harness/plans/compaction-cadence/archive/tasks/T005/diff.patch:425:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:37:+| `compaction_pause` | `{trigger, detail}` — `trigger` is one of `"task_count"`, `"wall_time"`, or `"pre_consult"`; `detail` carries trigger-specific fields (e.g. `tasks_since_pause`, `wall_minutes_since_pause`, `pending_remaining` for task-count/wall-time triggers, or `phase` for pre-consult) | `/z-implement-all` batch-settle (after halt-flush); `/z-review-all` Phase 3.7 (gates Phase 4 — `phase` payload value is `"review_all_phase_4"`); `/z-maintain-docs --audit` pre-consult breakpoint |
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:304: ## Phase 5 — Finalize
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:344: - `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:405:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:501:+     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:518:+     - Skip Phases 0–3.5. Jump directly to Phase 4.
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:532:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:544:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:548:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:568:+- Continue to Phase 4.
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:570: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:603: ## Phase 5 — Aggregate findings
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:681:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:787:+An unconditional breakpoint fires before the cross-LLM consultant batch spawns (between Phase 3.5 and Phase 4). No env var gate. An `AskUserQuestion` offers two options: "Pause for /clear" (exit, no state written) or "Proceed now" (write slug-scoped `.review_state.json` at `z-harness/plans/<slug>/.review_state.json` and continue). On the next invocation, if HEAD matches and the diff file is still present, the command fast-forwards to Phase 4 without re-running the expensive earlier phases.
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:1157: ## Phase 5 — Finalize
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:1203: - `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:1270:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:1366:+     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:1383:+     - Skip Phases 0–3.5. Jump directly to Phase 4.
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:1397:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:1409:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:1413:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:1433:+- Continue to Phase 4.
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:1435: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:1440: ## Phase 5 — Aggregate findings
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/cumulative.diff:1530:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/transcripts/final-review-2pronged.md:38:4. If all pass → fast-forward to Phase 4, restore environment from state fields, emit `review_resume_fast_forward`.
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/transcripts/final-review-2pronged.md:139:The Phase 3.7 breakpoint in `/z-review-all` fires *between Phase 3.5 (test run) and Phase 4 (consultant spawn)*, long before any halt collection. However, **this is NOT a violation** because:
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/transcripts/final-review-2pronged.md:144:4. The SPEC explicitly permits pre-consult breakpoints (line 71): "insert a new step between Phase 3.5 (test run) and Phase 4 (consultant spawn)".
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/transcripts/final-review-2pronged.md:296:- Fast-forward logic: "set all variables Phase 4 requires from state-file fields"
./z-harness/plans/compaction-cadence/archive/20260525T081221Z-review/transcripts/final-review-2pronged.md:300:The spec assumes git/bash don't fail during variable assignment. In practice, Phase 4 will fail immediately if `base_ref` is invalid (git will error), which is acceptable—the state file is corrupted. **No gap; fail-fast is appropriate.**
./z-harness/plans/z-audit-plan/SPEC.md:73:5. **Phase 4 — Merge and Synthesize Findings**
./z-harness/plans/z-audit-plan/SPEC.md:84:6. **Phase 5 — User Gate & Action**
./z-harness/plans/z-audit-plan/TASKS.md:8:- **Acceptance:** Valid YAML frontmatter description and argument hint. Complete detailed markdown body containing all phases (Phase 0 Setup, Phase 1 Reality Check, Phase 2 Design Check, Phase 3 Adversarial Review, Phase 4 Synthesis, Phase 5 User Gate).
./z-harness/plans/z-debug-rethink/BRAINSTORM.md:42:- Phase 4 becomes: **discriminating test design** — for each surviving hypothesis, design the cheapest test that would confirm OR refute (not just probe).
./z-harness/plans/z-debug-rethink/BRAINSTORM.md:43:- Phase 5 becomes: **batch experiment execution** — run all non-interfering tests in parallel; serialize interfering ones with explicit ordering.
./z-harness/plans/z-debug-rethink/BRAINSTORM.md:44:- New Phase 5b: **scoring + elimination** — update the registry; any hypothesis without a clear CONFIRMED requires a reason for ELIMINATED.
./z-harness/plans/z-debug-rethink/BRAINSTORM.md:166:- **Phase 4 (Consult) Shift:** Cross-LLM consultation must focus on deduplicating hypotheses and validating *quality of tests*, rather than just ranking hypotheses.
./z-harness/plans/z-debug-rethink/BRAINSTORM.md:167:- **Phase 5 (Isolate) Overhaul:** Becomes a "Batch Execution Engine." Instead of picking one hypothesis and running an experiment, run all validated discriminating tests, score the results matrix, and mathematically eliminate invalid hypotheses before looping back or proceeding to fix.
./z-harness/plans/doc-memories/SPEC.md:96:- `/z-init-docs` Phase 4 writes `docs/llm/TAGS.txt` with the 15-tag controlled seed plus an empty aliases section (with a header comment explaining the two-section format).
./z-harness/plans/doc-memories/SPEC.md:97:- `/z-suggest-memory` Phase 0 checks existence and bootstraps the file if missing (idempotent — same write logic as `/z-init-docs` Phase 4).
./z-harness/plans/doc-memories/SPEC.md:179:- Phase 4 gains a sibling step: after writing `docs/human/INDEX.md`, also write `docs/llm/MEMORIES-FLAT.md` with just the two-line header (no memory entries — none exist yet at init).
./z-harness/plans/doc-memories/SPEC.md:184:- New Phase 4.5 (after Phase 4 Apply, before Phase 5 Finalize): **regenerate MEMORIES-FLAT.md** from all current `docs/llm/<slug>.json` files. Algorithm: read each `<slug>.json`, emit one line per memory in the format above, sort lines lexicographically by `[<slug>]` then by `[<DATE>]` descending. Always overwrite the file (full regen, no incremental).
./z-harness/plans/doc-memories/SPEC.md:273:- **doc-updater returns `STATUS: not_enough_info` or errors.** /z-maintain-docs Phase 4 skips writing this concept; the on-disk JSON (including its `memories[]`) is **left untouched** at its prior state. Memories survive by inaction — no recovery path needed. Orchestrator surfaces the skip to the user via the existing Phase 4 status block.
./z-harness/plans/doc-memories/PLAN.md:42:2. **MEMORIES-FLAT.md generation logic.** Create `scripts/regenerate-memories-flat.py` (signature in SPEC). Extend `skills/z-init-docs/SKILL.md` (initial empty file with header) and `skills/z-maintain-docs/SKILL.md` (Phase 4.5 regenerator) — both shell out to the helper.
./z-harness/plans/doc-memories/TASKS.md:60:**Description:** In Phase 4 (after writing `docs/human/INDEX.md`), shell out to `python3 scripts/regenerate-memories-flat.py --repo-root <root>` to create the file with just the header lines (no memories exist at init). Phase 6 summary mentions the new file.
./z-harness/plans/doc-memories/TASKS.md:63:- [ ] Phase 4 invokes the helper.
./z-harness/plans/doc-memories/TASKS.md:68:## T005 — z-maintain-docs: Phase 4.5 regen + Phase 3 stale UX [x]
./z-harness/plans/doc-memories/TASKS.md:75:- Insert Phase 4.5 (after Phase 4 Apply): unconditional `python3 scripts/regenerate-memories-flat.py` invocation.
./z-harness/plans/doc-memories/TASKS.md:81:- [ ] Phase 4.5 documented.
./z-harness/plans/doc-memories/tests/validate-memory.py:3:Memory schema validator — mirrors /z-suggest-memory Phase 4 validation logic.
./z-harness/plans/doc-memories/archive/20260523T060110Z-doc-memories/decisions.md:87:Regenerated by: (i) /z-init-docs Phase 4 (initial creation, possibly empty), (ii) /z-maintain-docs Phase 4 (after apply), (iii) /z-suggest-memory itself after writing a new memory. Always full regen from all `docs/llm/<slug>.json` (no incremental — file is small enough).
./z-harness/plans/doc-memories/archive/20260523T060110Z-doc-memories/SPEC.md:137:- Phase 4 gains a sibling step: after writing `docs/human/INDEX.md`, also write `docs/llm/MEMORIES-FLAT.md` with just the two-line header (no memory entries — none exist yet at init).
./z-harness/plans/doc-memories/archive/20260523T060110Z-doc-memories/SPEC.md:142:- New Phase 4.5 (after Phase 4 Apply, before Phase 5 Finalize): **regenerate MEMORIES-FLAT.md** from all current `docs/llm/<slug>.json` files. Algorithm: read each `<slug>.json`, emit one line per memory in the format above, sort lines lexicographically by `[<slug>]` then by `[<DATE>]` descending. Always overwrite the file (full regen, no incremental).
./research/hermes-agent/website/docs/developer-guide/context-compression-and-caching.md:192:### Phase 4: Assemble Compressed Messages
./z-harness/plans/doc-memories/archive/20260523T060110Z-doc-memories/PLAN.md:42:2. **MEMORIES-FLAT.md generation logic.** Create `scripts/regenerate-memories-flat.py` (signature in SPEC). Extend `skills/z-init-docs/SKILL.md` (initial empty file with header) and `skills/z-maintain-docs/SKILL.md` (Phase 4.5 regenerator) — both shell out to the helper.
./z-harness/plans/doc-memories/archive/20260523T060110Z-doc-memories/phase3-decisions-final.md:57:- **Gemini:** (d) + escape hatch for cross-cutting / new-concept memories.
./z-harness/plans/doc-memories/archive/20260523T060110Z-doc-memories/phase3-decisions-final.md:60:- **One reason Gemini's "GLOBAL" might be wrong:** a "GLOBAL" memories bucket becomes a junk drawer. **Counter:** Gemini's instinct is right but "GLOBAL" is the wrong solution — the right escape hatch is "create a new concept" via /z-init-docs handoff. That way cross-cutting concerns get their own concept (which they deserved anyway).
./z-harness/plans/doc-memories/archive/20260523T060110Z-doc-memories/phase3-decisions-final.md:81:**None.** All five decisions accept the robust long-lasting option. No Phase 5 shortcut approval needed.
./z-harness/plans/doc-memories/archive/20260523T060110Z-doc-memories/TASKS.md:60:**Description:** In Phase 4 (after writing `docs/human/INDEX.md`), shell out to `python3 scripts/regenerate-memories-flat.py --repo-root <root>` to create the file with just the header lines (no memories exist at init). Phase 6 summary mentions the new file.
./z-harness/plans/doc-memories/archive/20260523T060110Z-doc-memories/TASKS.md:63:- [ ] Phase 4 invokes the helper.
./z-harness/plans/doc-memories/archive/20260523T060110Z-doc-memories/TASKS.md:68:## T005 — z-maintain-docs: Phase 4.5 regen + Phase 3 stale UX
./z-harness/plans/doc-memories/archive/20260523T060110Z-doc-memories/TASKS.md:75:- Insert Phase 4.5 (after Phase 4 Apply): unconditional `python3 scripts/regenerate-memories-flat.py` invocation.
./z-harness/plans/doc-memories/archive/20260523T060110Z-doc-memories/TASKS.md:81:- [ ] Phase 4.5 documented.
./z-harness/plans/doc-memories/archive/20260523T060110Z-doc-memories/phase1-context.md:11:| `skills/z-init-docs/SKILL.md` | Phase 4 — initialize empty `docs/llm/MEMORIES-FLAT.md`. |
./z-harness/plans/doc-memories/archive/20260523T060110Z-doc-memories/phase1-context.md:12:| `skills/z-maintain-docs/SKILL.md` | New Phase 4.5 — regenerate `MEMORIES-FLAT.md` from all `docs/llm/<slug>.json` after the apply phase. New staleness flag: memories with `date` older than 18 months → surface in dry-run preview for human review. |
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/findings.md:28:- **Memory preservation on `doc-updater STATUS: not_enough_info`.** SPEC defines memory preservation only in the doc-updater success path. If doc-updater can't refresh (returns `not_enough_info` or errors), z-maintain-docs Phase 4 skips the write — but the SPEC is silent on whether existing memories in the unrefreshed JSON should survive (they will, since the JSON wasn't touched) or whether the orchestrator should attempt a memories-only preservation write. *One reason it might be wrong:* if doc-updater doesn't write, the JSON is left untouched and memories are de facto preserved by inaction — so this might be a documentation gap not a data-loss bug. Worth a one-line SPEC clarification: "on doc-updater failure, the JSON is left at prior state; memories survive by inaction; no recovery path needed."
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:336: ## Phase 5 — Copy default `.z-harness-rsync-exclude`
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:383:+- **Delete** — splice out `memories[index]` from the concept JSON using an atomic write, then log the deletion. MEMORIES-FLAT.md is **NOT** regenerated inline; Phase 4.5 handles regen after all deletes apply.
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:421:+## Phase 4.5 — Regenerate MEMORIES-FLAT.md
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:423:+After all accepted concept files have been written in Phase 4, unconditionally regenerate `docs/llm/MEMORIES-FLAT.md` from all current `docs/llm/<slug>.json` files:
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:431:+If the script exits non-zero, surface the error to the user and halt (do not proceed to Phase 5 with a potentially corrupt MEMORIES-FLAT.md).
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:433: ## Phase 5 — Finalize
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:633:+In delete mode, jump directly to Phase 5 (Write) after resolving the target concept from the `--delete <slug>` argument — no collection needed.
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:717:+Free-text input. Constraints (validated in Phase 4; show them inline in the question):
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:753:+## Phase 4 — Validate
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:785:+## Phase 5 — Write
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:829:+If `--dry-run` is active, skip the actual write in all three modes (already handled in Phase 4; this is a belt-and-suspenders note).
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:1139:+<filled in during Phase 5>
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:1147:+## Phase 4 — (Optional) cross-LLM consult on proposals
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:1164:+## Phase 5 — Discussion with the user
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:2071:+Memory schema validator — mirrors /z-suggest-memory Phase 4 validation logic.
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:2290:+| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:2313:+| `cluster_files_inconsistent` | `/z-plan-split` Phase 4 when `FILES_TOUCHED` ↔ TASKS.md disagree |
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:2314:+| `total_cluster_failure` | `/z-plan-split` Phase 3 or Phase 4 when every cluster ends `failed` |
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:2315:+| `overlap_detected` | `/z-plan-split` Phase 4 (per overlapping path) |
./z-harness/plans/doc-memories/archive/20260523T174951Z-review/cumulative.diff:2316:+| `overlap_index_rebuilt` | `/z-plan-split` Phase 4 after any post-Phase-3 cluster demotion |
./z-harness/plans/doc-memories/archive/tasks/T007/diff.patch:55:+In delete mode, jump directly to Phase 5 (Write) after resolving the target concept from the `--delete <slug>` argument — no collection needed.
./z-harness/plans/doc-memories/archive/tasks/T007/diff.patch:139:+Free-text input. Constraints (validated in Phase 4; show them inline in the question):
./z-harness/plans/doc-memories/archive/tasks/T007/diff.patch:175:+## Phase 4 — Validate
./z-harness/plans/doc-memories/archive/tasks/T007/diff.patch:207:+## Phase 5 — Write
./z-harness/plans/doc-memories/archive/tasks/T007/diff.patch:251:+If `--dry-run` is active, skip the actual write in all three modes (already handled in Phase 4; this is a belt-and-suspenders note).
./z-harness/plans/doc-memories/archive/tasks/T012/diff.patch:82:+| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
./z-harness/plans/doc-memories/archive/tasks/T012/diff.patch:105:+| `cluster_files_inconsistent` | `/z-plan-split` Phase 4 when `FILES_TOUCHED` ↔ TASKS.md disagree |
./z-harness/plans/doc-memories/archive/tasks/T012/diff.patch:106:+| `total_cluster_failure` | `/z-plan-split` Phase 3 or Phase 4 when every cluster ends `failed` |
./z-harness/plans/doc-memories/archive/tasks/T012/diff.patch:107:+| `overlap_detected` | `/z-plan-split` Phase 4 (per overlapping path) |
./z-harness/plans/doc-memories/archive/tasks/T012/diff.patch:108:+| `overlap_index_rebuilt` | `/z-plan-split` Phase 4 after any post-Phase-3 cluster demotion |
./research/hermes-agent/hermes_cli/profiles.py:790:    # Phase 4: when running inside a container under s6, register the
./research/hermes-agent/hermes_cli/profiles.py:914:    # 1b. Phase 4: unregister the s6 service slot (container path).
./z-harness/plans/doc-memories/archive/tasks/T004/review.response.md:6:- ✓ Phase 4 invokes the helper: bash block calls python3 scripts/regenerate-memories-flat.py --repo-root "$(pwd)"
./z-harness/plans/doc-memories/archive/tasks/T004/review.response.md:11:- Phase 4 adds a sibling step after INDEX.md generation (correct positioning)
./z-harness/plans/doc-memories/archive/tasks/T004/review.response.md:23:**No blockers or majors found.** The implementation is correct and satisfies both acceptance criteria. If error-handling verbosity becomes important, Phase 4 could add explicit checks for the exit code, but the current approach aligns with the specs intent.
./z-harness/plans/doc-memories/archive/tasks/T004/diff.patch:15: ## Phase 5 — Copy default `.z-harness-rsync-exclude`
./z-harness/plans/doc-memories/archive/tasks/T005/review.prompt.md:1:You are reviewing code that Claude just wrote for task T005: z-maintain-docs SKILL.md — Phase 4.5 unconditional regenerate-memories-flat.py call; Phase 3 "Stale memories" UX with Keep/Edit/Delete + memory_deleted event; Phase 3 surfaces TAG_COLLISIONS
./z-harness/plans/doc-memories/archive/tasks/T005/review.prompt.md:4:- Phase 4.5 documented
./z-harness/plans/doc-memories/archive/tasks/T005/review.prompt.md:64:+## Phase 4.5 — Regenerate MEMORIES-FLAT.md
./z-harness/plans/doc-memories/archive/tasks/T005/review.prompt.md:66:+After all accepted concept files have been written in Phase 4, unconditionally regenerate `docs/llm/MEMORIES-FLAT.md` from all current `docs/llm/<slug>.json` files:
./z-harness/plans/doc-memories/archive/tasks/T005/review.prompt.md:74:+If the script exits non-zero, surface the error to the user and halt (do not proceed to Phase 5 with a potentially corrupt MEMORIES-FLAT.md).
./z-harness/plans/doc-memories/archive/tasks/T005/review.prompt.md:76: ## Phase 5 — Finalize
./z-harness/plans/doc-memories/archive/tasks/T005/diff-v1.patch:55:+## Phase 4.5 — Regenerate MEMORIES-FLAT.md
./z-harness/plans/doc-memories/archive/tasks/T005/diff-v1.patch:57:+After all accepted concept files have been written in Phase 4, unconditionally regenerate `docs/llm/MEMORIES-FLAT.md` from all current `docs/llm/<slug>.json` files:
./z-harness/plans/doc-memories/archive/tasks/T005/diff-v1.patch:65:+If the script exits non-zero, surface the error to the user and halt (do not proceed to Phase 5 with a potentially corrupt MEMORIES-FLAT.md).
./z-harness/plans/doc-memories/archive/tasks/T005/diff-v1.patch:67: ## Phase 5 — Finalize
./z-harness/plans/doc-memories/archive/tasks/T005/delta-v2.patch:29:++- **Delete** — splice out `memories[index]` from the concept JSON using an atomic write, then log the deletion. MEMORIES-FLAT.md is **NOT** regenerated inline; Phase 4.5 handles regen after all deletes apply.
./z-harness/plans/doc-memories/archive/tasks/T005/review.response.md:5:1. **Phase 3 Delete vs Phase 4.5 regeneration conflict** (lines 129, 162-173): Phase 3 Delete explicitly calls regenerate-memories-flat.py inline, but Phase 4.5 says it "unconditionally" regenerates and runs "whenever a memory was deleted during Phase 3." This creates ambiguity: does regenerate-memories-flat.py run twice (redundant), or should Phase 3 skip it and defer to Phase 4.5? The phrase "This step runs in both --apply mode and whenever a memory was deleted" suggests Phase 4.5 is the sole regeneration point, making Phase 3's inline regenerate call incorrect.
./z-harness/plans/doc-memories/archive/tasks/T005/diff.patch:35:+- **Delete** — splice out `memories[index]` from the concept JSON using an atomic write, then log the deletion. MEMORIES-FLAT.md is **NOT** regenerated inline; Phase 4.5 handles regen after all deletes apply.
./z-harness/plans/doc-memories/archive/tasks/T005/diff.patch:73:+## Phase 4.5 — Regenerate MEMORIES-FLAT.md
./z-harness/plans/doc-memories/archive/tasks/T005/diff.patch:75:+After all accepted concept files have been written in Phase 4, unconditionally regenerate `docs/llm/MEMORIES-FLAT.md` from all current `docs/llm/<slug>.json` files:
./z-harness/plans/doc-memories/archive/tasks/T005/diff.patch:83:+If the script exits non-zero, surface the error to the user and halt (do not proceed to Phase 5 with a potentially corrupt MEMORIES-FLAT.md).
./z-harness/plans/doc-memories/archive/tasks/T005/diff.patch:85: ## Phase 5 — Finalize
./z-harness/plans/doc-memories/archive/tasks/T011/diff.patch:803:+Memory schema validator — mirrors /z-suggest-memory Phase 4 validation logic.
./z-harness/plans/doc-memories/archive/tasks/T010/diff-v1.patch:110:+<filled in during Phase 5>
./z-harness/plans/doc-memories/archive/tasks/T010/diff-v1.patch:118:+## Phase 4 — (Optional) cross-LLM consult on proposals
./z-harness/plans/doc-memories/archive/tasks/T010/diff-v1.patch:135:+## Phase 5 — Discussion with the user
./z-harness/plans/doc-memories/archive/tasks/T010/diff.patch:110:+<filled in during Phase 5>
./z-harness/plans/doc-memories/archive/tasks/T010/diff.patch:118:+## Phase 4 — (Optional) cross-LLM consult on proposals
./z-harness/plans/doc-memories/archive/tasks/T010/diff.patch:135:+## Phase 5 — Discussion with the user
./z-harness/plans/doc-memories/archive/tasks/T100/diff-v1.patch:196: ## Phase 5 — Copy default `.z-harness-rsync-exclude`
./z-harness/plans/doc-memories/archive/tasks/T100/diff-v1.patch:243:+- **Delete** — splice out `memories[index]` from the concept JSON using an atomic write, then log the deletion. MEMORIES-FLAT.md is **NOT** regenerated inline; Phase 4.5 handles regen after all deletes apply.
./z-harness/plans/doc-memories/archive/tasks/T100/diff-v1.patch:296:+## Phase 4.5 — Regenerate MEMORIES-FLAT.md
./z-harness/plans/doc-memories/archive/tasks/T100/diff-v1.patch:298:+After all accepted concept files have been written in Phase 4, unconditionally regenerate `docs/llm/MEMORIES-FLAT.md` from all current `docs/llm/<slug>.json` files:
./z-harness/plans/doc-memories/archive/tasks/T100/diff-v1.patch:306:+If the script exits non-zero, surface the error to the user and halt (do not proceed to Phase 5 with a potentially corrupt MEMORIES-FLAT.md).
./z-harness/plans/doc-memories/archive/tasks/T100/diff-v1.patch:308: ## Phase 5 — Finalize
./z-harness/plans/doc-memories/archive/tasks/T100/diff-v1.patch:352:+If it does **not** exist, write it now with the same controlled-seed content that `/z-init-docs` Phase 4 writes (atomic write via tmpfile + `os.replace()`):
./z-harness/plans/doc-memories/archive/tasks/T100/diff-v1.patch:416:+In delete mode, jump directly to Phase 5 (Write) after resolving the target concept from the `--delete <slug>` argument — no collection needed.
./z-harness/plans/doc-memories/archive/tasks/T100/diff-v1.patch:500:+Free-text input. Constraints (validated in Phase 4; show them inline in the question):
./z-harness/plans/doc-memories/archive/tasks/T100/diff-v1.patch:550:+## Phase 4 — Validate
./z-harness/plans/doc-memories/archive/tasks/T100/diff-v1.patch:582:+## Phase 5 — Write
./z-harness/plans/doc-memories/archive/tasks/T100/diff-v1.patch:626:+If `--dry-run` is active, skip the actual write in all three modes (already handled in Phase 4; this is a belt-and-suspenders note).
./z-harness/plans/doc-memories/archive/tasks/T100/diff.patch:196: ## Phase 5 — Copy default `.z-harness-rsync-exclude`
./z-harness/plans/doc-memories/archive/tasks/T100/diff.patch:280:+- **Delete** — splice out `memories[index]` from the concept JSON using an atomic write, then log the deletion. MEMORIES-FLAT.md is **NOT** regenerated inline; Phase 4.5 handles regen after all deletes apply.
./z-harness/plans/doc-memories/archive/tasks/T100/diff.patch:333:+## Phase 4.5 — Regenerate MEMORIES-FLAT.md
./z-harness/plans/doc-memories/archive/tasks/T100/diff.patch:335:+After all accepted concept files have been written in Phase 4, unconditionally regenerate `docs/llm/MEMORIES-FLAT.md` from all current `docs/llm/<slug>.json` files:
./z-harness/plans/doc-memories/archive/tasks/T100/diff.patch:343:+If the script exits non-zero, surface the error to the user and halt (do not proceed to Phase 5 with a potentially corrupt MEMORIES-FLAT.md).
./z-harness/plans/doc-memories/archive/tasks/T100/diff.patch:345: ## Phase 5 — Finalize
./z-harness/plans/doc-memories/archive/tasks/T100/diff.patch:389:+If it does **not** exist, write it now with the same controlled-seed content that `/z-init-docs` Phase 4 writes (atomic write via tmpfile + `os.replace()`):
./z-harness/plans/doc-memories/archive/tasks/T100/diff.patch:453:+In delete mode, jump directly to Phase 5 (Write) after resolving the target concept from the `--delete <slug>` argument — no collection needed.
./z-harness/plans/doc-memories/archive/tasks/T100/diff.patch:537:+Free-text input. Constraints (validated in Phase 4; show them inline in the question):
./z-harness/plans/doc-memories/archive/tasks/T100/diff.patch:587:+## Phase 4 — Validate
./z-harness/plans/doc-memories/archive/tasks/T100/diff.patch:619:+## Phase 5 — Write
./z-harness/plans/doc-memories/archive/tasks/T100/diff.patch:663:+If `--dry-run` is active, skip the actual write in all three modes (already handled in Phase 4; this is a belt-and-suspenders note).
./z-harness/plans/plan-bail-router/PLAN.md:126:### Phase 4 - Mirror Skill Checklists
./z-harness/plans/plan-bail-router/PLAN.md:140:### Phase 5 - Docs and Memory Updates
./z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/PLAN.md:124:### Phase 4 - Mirror Skill Checklists
./z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/PLAN.md:138:### Phase 5 - Docs and Memory Updates
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/findings.md:11:- [from codex] `/z-audit-plan` Phase 5 still contains imperative action wording that can violate read-only/contextual-only semantics.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/findings.md:13:  Recommendation: Convert those Phase 5 choices into route-decision handoffs or clearly say they are recommendations only; write `route-decision.md`, emit `plan_route_decision`, present switch/continue/abandon, and stop.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/findings.md:88:- Items only Codex flagged: `/z-audit-plan` Phase 5 read-only risk, `/z-plan-split` setup variable drift, route artifact template incompleteness, existing-plan discovery drift, no-plan archive path, route-chain handoff.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:106: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:261: - `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:322:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:564:+An unconditional breakpoint fires before the cross-LLM consultant batch spawns (between Phase 3.5 and Phase 4). No env var gate. An `AskUserQuestion` offers two options: "Pause for /clear" (exit, no state written) or "Proceed now" (write slug-scoped `.review_state.json` at `z-harness/plans/<slug>/.review_state.json` and continue). On the next invocation, if HEAD matches and the diff file is still present, the command fast-forwards to Phase 4 without re-running the expensive earlier phases.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:625:+- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:626:+- `skills/z-maintain-docs/SKILL.md:1` — `z-maintain-docs` — Refreshes stale docs. Phase 2 spawns `doc-updater` subagents with `dedup_tags: true`. Phase 3 surfaces stale memories and TAG_COLLISIONS. Phase 4.5 regenerates MEMORIES-FLAT.md after every write. Supports `--apply` and `--audit` flags.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:628:+- `skills/z-plan-split/SKILL.md:1` — `z-plan-split` — Pre-emptive scope splitter into 2-6 clusters. Enforces kebab-slug security gate. Phase 4 reconciles file-path overlaps from TASKS.md (canonical) against `FILES_TOUCHED` summary. Writes MANIFEST.md and SHARED-CONCERNS.md. MANIFEST uses stable `cluster_id` (C1…CN) for telemetry and `cluster_slug` for on-disk paths.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:630:+- `skills/z-research/SKILL.md:1` — `z-research` — Terrain-mapping pre-plan research. Cost gate at Phase 0 (up to 3 Explores or 1). Phase 4 bundled cross-LLM critique. RESEARCH.md has mandatory `## No-recommendation` section with locked canonical text.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:656:+- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:665:+  Read `skills/z-amend/SKILL.md` Phase 4 (user gate) and Phase 6 (propagation) for the full checklist.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:1535: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:1794: ## Phase 5 — Finalize
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:1944: - `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:2005:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:2132:+     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:2149:+     - Skip Phases 0–3.5. Jump directly to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:2163:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:2175:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:2179:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:2199:+- Continue to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:2201: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:2206: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:2296:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:2449: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:2643: ## Phase 5 — Finalize
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:2813: - `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:2874:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:3001:+     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:3018:+     - Skip Phases 0–3.5. Jump directly to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:3032:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:3044:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:3048:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:3068:+- Continue to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:3070: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:3103: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:3181:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:3530: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:3789: ## Phase 5 — Finalize
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:3938: - `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:3999:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:4126:+     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:4143:+     - Skip Phases 0–3.5. Jump directly to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:4157:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:4169:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:4173:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:4193:+- Continue to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:4195: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:4200: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:4290:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:4443: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:4637: ## Phase 5 — Finalize
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:4807: - `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:4868:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:4995:+     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:5012:+     - Skip Phases 0–3.5. Jump directly to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:5026:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:5038:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:5042:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:5062:+- Continue to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:5064: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:5097: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:5175:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:5780: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:6039: ## Phase 5 — Finalize
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:6202: - `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:6263:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:6390:+     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:6407:+     - Skip Phases 0–3.5. Jump directly to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:6421:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:6433:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:6437:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:6457:+- Continue to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:6459: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:6464: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:6554:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:6862: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:7121: ## Phase 5 — Finalize
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:7291: - `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:7352:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:7479:+     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:7496:+     - Skip Phases 0–3.5. Jump directly to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:7510:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:7522:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:7526:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:7546:+- Continue to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:7548: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:7553: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:7643:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:7790: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:7952: - `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:8019:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:8422:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:8461:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:8942:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:8981:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:9148:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:9187:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:9668:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:9707:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:9875:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:9914:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:10079:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:10118:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:10599:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:10638:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:10806:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff:10845:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:479:### Phase 4 - Mirror Skill Checklists
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:493:### Phase 5 - Docs and Memory Updates
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:1356:564:+An unconditional breakpoint fires before the cross-LLM consultant batch spawns (between Phase 3.5 and Phase 4). No env var gate. An `AskUserQuestion` offers two options: "Pause for /clear" (exit, no state written) or "Proceed now" (write slug-scoped `.review_state.json` at `z-harness/plans/<slug>/.review_state.json` and continue). On the next invocation, if HEAD matches and the diff file is still present, the command fast-forwards to Phase 4 without re-running the expensive earlier phases.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:1978:## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:1995:## Phase 5 — Codex review (MANDATORY safety gate)
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:2177:## Phase 4 — Synthesize + push back
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:2183:3. **Flag shortcuts.** If any option is a shortcut over the robust long-lasting solution, mark it explicitly — needs Phase 5 user approval.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:2184:4. **Cross-LLM disagreement.** If Gemini and Codex disagree substantively, surface the disagreement to the user in Phase 5 — do not silently pick one.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:2186:## Phase 5 — Present + approve
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:2384:- `ready` — Phase 5 finalized with all clusters ready.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:2385:- `partial` — Phase 5 finalized with ≥1 cluster ready and ≥1 failed.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:2391:- `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:2596:Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:2761:3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:2765:## Phase 4 — Final clarifications
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:2769:## Phase 5 — Present + approve
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:3234:## Phase 4 — Bundled cross-LLM critique
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:3382:## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:3421:## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:3754:Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:3894:- `ready` — Phase 5 finalized with all clusters ready.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:3895:- `partial` — Phase 5 finalized with ≥1 cluster ready and ≥1 failed.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:3901:- `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:4104:Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:4187:Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:4275:Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:4861:- evidence: Phase 5 offers actions that violate the spec invariants: “Proceed as-is” says to “start implementation,” and “Reject & Re-plan” says to “Discard current plan artifacts and rerun `/z-plan`.” The spec requires `/z-audit-plan` to remain read-only, use contextual route exits, never auto-execute another command, and stop if the user switches.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:4862:- recommendation: Change Phase 5 options into route-decision handoffs: write `route-decision.md`, emit `plan_route_decision`, present switch/continue/abandon, and stop after presenting the exact next invocation. “Proceed as-is” should end the audit only, not start implementation.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:4917:- evidence: Phase 5 offers actions that violate the spec invariants: “Proceed as-is” says to “start implementation,” and “Reject & Re-plan” says to “Discard current plan artifacts and rerun `/z-plan`.” The spec requires `/z-audit-plan` to remain read-only, use contextual route exits, never auto-execute another command, and stop if the user switches.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/004-codex-final-review-2pronged.response.md:4918:- recommendation: Change Phase 5 options into route-decision handoffs: write `route-decision.md`, emit `plan_route_decision`, present switch/continue/abandon, and stop after presenting the exact next invocation. “Proceed as-is” should end the audit only, not start implementation.
./research/hermes-agent/hermes_cli/container_boot.py:12:Dockerfile (Phase 4 Task 4.0). Runs as root after 01-hermes-setup
./research/hermes-agent/hermes_cli/container_boot.py:231:        # (which routes through the Phase 4
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:576:### Phase 4 - Mirror Skill Checklists
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:590:### Phase 5 - Docs and Memory Updates
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:1047: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:1202: - `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:1263:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:1505:+An unconditional breakpoint fires before the cross-LLM consultant batch spawns (between Phase 3.5 and Phase 4). No env var gate. An `AskUserQuestion` offers two options: "Pause for /clear" (exit, no state written) or "Proceed now" (write slug-scoped `.review_state.json` at `z-harness/plans/<slug>/.review_state.json` and continue). On the next invocation, if HEAD matches and the diff file is still present, the command fast-forwards to Phase 4 without re-running the expensive earlier phases.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:1566:+- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:1567:+- `skills/z-maintain-docs/SKILL.md:1` — `z-maintain-docs` — Refreshes stale docs. Phase 2 spawns `doc-updater` subagents with `dedup_tags: true`. Phase 3 surfaces stale memories and TAG_COLLISIONS. Phase 4.5 regenerates MEMORIES-FLAT.md after every write. Supports `--apply` and `--audit` flags.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:1569:+- `skills/z-plan-split/SKILL.md:1` — `z-plan-split` — Pre-emptive scope splitter into 2-6 clusters. Enforces kebab-slug security gate. Phase 4 reconciles file-path overlaps from TASKS.md (canonical) against `FILES_TOUCHED` summary. Writes MANIFEST.md and SHARED-CONCERNS.md. MANIFEST uses stable `cluster_id` (C1…CN) for telemetry and `cluster_slug` for on-disk paths.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:1571:+- `skills/z-research/SKILL.md:1` — `z-research` — Terrain-mapping pre-plan research. Cost gate at Phase 0 (up to 3 Explores or 1). Phase 4 bundled cross-LLM critique. RESEARCH.md has mandatory `## No-recommendation` section with locked canonical text.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:1597:+- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:1606:+  Read `skills/z-amend/SKILL.md` Phase 4 (user gate) and Phase 6 (propagation) for the full checklist.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:2476: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:2735: ## Phase 5 — Finalize
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:2885: - `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:2946:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3073:+     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3090:+     - Skip Phases 0–3.5. Jump directly to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3104:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3116:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3120:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3140:+- Continue to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3142: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3147: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3237:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3390: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3584: ## Phase 5 — Finalize
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3754: - `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3815:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3942:+     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3959:+     - Skip Phases 0–3.5. Jump directly to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3973:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3985:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3989:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:4009:+- Continue to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:4011: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:4044: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:4122:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:4471: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:4730: ## Phase 5 — Finalize
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:4879: - `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:4940:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5067:+     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5084:+     - Skip Phases 0–3.5. Jump directly to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5098:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5110:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5114:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5134:+- Continue to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5136: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5141: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5231:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5384: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5578: ## Phase 5 — Finalize
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5748: - `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5809:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5936:+     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5953:+     - Skip Phases 0–3.5. Jump directly to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5967:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5979:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5983:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:6003:+- Continue to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:6005: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:6038: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:6116:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:6721: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:6980: ## Phase 5 — Finalize
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7143: - `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7204:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7331:+     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7348:+     - Skip Phases 0–3.5. Jump directly to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7362:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7374:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7378:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7398:+- Continue to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7400: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7405: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7495:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7803: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8062: ## Phase 5 — Finalize
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8232: - `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8293:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8420:+     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8437:+     - Skip Phases 0–3.5. Jump directly to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8451:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8463:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8467:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8487:+- Continue to Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8489: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8494: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8584:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8731: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8893: - `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8960:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:9363:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:9402:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:9883:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:9922:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:10089:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:10128:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:10609:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:10648:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:10816:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:10855:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:11020:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:11059:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:11540:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:11579:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:11747:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:11786:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/20260524T235017Z-amend-plan-bail-router/z-harness/plans/plan-bail-router/PLAN.md.diff:129:+### Phase 4 - Mirror Skill Checklists
./z-harness/plans/plan-bail-router/archive/20260524T235017Z-amend-plan-bail-router/z-harness/plans/plan-bail-router/PLAN.md.diff:143:+### Phase 5 - Docs and Memory Updates
./research/hermes-agent/hermes_cli/service_manager.py:14:profile create/delete hooks (Phase 4) and the s6 dispatch path in
./research/hermes-agent/hermes_cli/service_manager.py:199:    (the Phase 4 profile create/delete hooks).
./research/hermes-agent/hermes_cli/service_manager.py:316:# runs inside the container (Phase 4). Static services (main-hermes, dashboard)
./research/hermes-agent/hermes_cli/service_manager.py:332:# notably our Phase 4 profile create/delete hooks — inherits the
./research/hermes-agent/hermes_cli/service_manager.py:738:        which the Phase 4 reconciliation path uses via a ``down``
./z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:31:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:123:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:215:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:307:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:399:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:491:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:589:+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:256:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:257:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:312:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:397:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:398:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:484:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:485:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:571:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:572:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:658:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:659:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:745:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:746:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:837:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:838:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./research/hermes-agent/hermes_cli/gateway.py:984:        # Phase 4: report s6 supervision when running under our /init.
./research/hermes-agent/hermes_cli/gateway.py:5040:    The s6 service slot was created either by the Phase 4 profile-create
./research/hermes-agent/hermes_cli/gateway.py:5216:            # Phase 4: inside a container with s6 the gateway service is
./research/hermes-agent/hermes_cli/gateway.py:5282:        # Phase 4: inside a container with s6, dispatch via the service
./research/hermes-agent/hermes_cli/gateway.py:5340:        # Phase 4: inside a container with s6, dispatch via the service
./research/hermes-agent/hermes_cli/gateway.py:5418:        # Phase 4: inside a container with s6, dispatch via the service
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:274:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:275:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:330:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:415:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:416:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:502:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:503:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:589:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:590:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:676:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:677:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:763:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:764:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:855:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:856:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:1020:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:1080:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:1140:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:1200:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:1260:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:1320:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:1380:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:1446:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:176:+- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:177:+- `skills/z-maintain-docs/SKILL.md:1` — `z-maintain-docs` — Refreshes stale docs. Phase 2 spawns `doc-updater` subagents with `dedup_tags: true`. Phase 3 surfaces stale memories and TAG_COLLISIONS. Phase 4.5 regenerates MEMORIES-FLAT.md after every write. Supports `--apply` and `--audit` flags.
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:179:+- `skills/z-plan-split/SKILL.md:1` — `z-plan-split` — Pre-emptive scope splitter into 2-6 clusters. Enforces kebab-slug security gate. Phase 4 reconciles file-path overlaps from TASKS.md (canonical) against `FILES_TOUCHED` summary. Writes MANIFEST.md and SHARED-CONCERNS.md. MANIFEST uses stable `cluster_id` (C1…CN) for telemetry and `cluster_slug` for on-disk paths.
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:181:+- `skills/z-research/SKILL.md:1` — `z-research` — Terrain-mapping pre-plan research. Cost gate at Phase 0 (up to 3 Explores or 1). Phase 4 bundled cross-LLM critique. RESEARCH.md has mandatory `## No-recommendation` section with locked canonical text.
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:207:+- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
./z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:216:+  Read `skills/z-amend/SKILL.md` Phase 4 (user gate) and Phase 6 (propagation) for the full checklist.
./z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:49:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:50:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:105:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:190:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:191:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:277:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:278:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:364:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:365:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:451:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:452:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:538:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:539:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:630:-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:631:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:26:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:86:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:146:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:206:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:266:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:326:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:386:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:452:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/z-fix-hypothesis-driven/SPEC.md:41:7. **Phase 4 — Synthesize + push back.** For each recommendation, articulate one reason it might be wrong. Flag shortcuts. Cross-LLM disagreement is surfaced to the user in Phase 5.
./z-harness/plans/z-fix-hypothesis-driven/SPEC.md:42:8. **Phase 5 — Approve.** `AskUserQuestion` with `approve | modify | abandon` options. Push-notify if policy permits.
./z-harness/plans/z-fix-hypothesis-driven/SPEC.md:88:8. **Phase 4 — Build `## Test Matrix` section.** For each surviving hypothesis, write one matrix row with columns: `id | claim | proposed_by | overlap | prior | test | cost | parallel | status`. Schema header line documented at top of section per Codex's recommendation. Prior bucket assigned mechanically from overlap_count: `3→high, 2→med, 1→low`. Initial status = `active`.
./z-harness/plans/z-fix-hypothesis-driven/SPEC.md:89:9. **Phase 5 — Compute test order (consensus-first + outlier carve-out, D6).** Sort hypotheses by overlap_count descending. **Always insert** the top 2 unique-to-one-model (overlap=1) hypotheses near the front of the order, even if their prior is `low`. This is the groupthink mitigation.
./z-harness/plans/z-fix-hypothesis-driven/TASKS.md:90:- [ ] Phase 4 builds Test Matrix with schema header documented at top of section.
./z-harness/plans/z-fix-hypothesis-driven/TASKS.md:91:- [ ] Phase 5 test-order rule: consensus-first + forced outlier carve-out (top 2 overlap=1 rows always tested early).
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:390: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:655:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:712: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:949: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:1156:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:1256: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:1650: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:1914:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:1971: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:2208: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:2415:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:2515: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:3165: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:3443:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:3500: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:3865: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:4150:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:4207: ## Phase 5 — Aggregate findings
./z-harness/plans/z-fix-hypothesis-driven/archive/20260524T061903Z-z-fix-hypothesis-driven/SPEC.md:41:7. **Phase 4 — Synthesize + push back.** For each recommendation, articulate one reason it might be wrong. Flag shortcuts. Cross-LLM disagreement is surfaced to the user in Phase 5.
./z-harness/plans/z-fix-hypothesis-driven/archive/20260524T061903Z-z-fix-hypothesis-driven/SPEC.md:42:8. **Phase 5 — Approve.** `AskUserQuestion` with `approve | modify | abandon` options. Push-notify if policy permits.
./z-harness/plans/z-fix-hypothesis-driven/archive/20260524T061903Z-z-fix-hypothesis-driven/SPEC.md:88:8. **Phase 4 — Build `## Test Matrix` section.** For each surviving hypothesis, write one matrix row with columns: `id | claim | proposed_by | overlap | prior | test | cost | parallel | status`. Schema header line documented at top of section per Codex's recommendation. Prior bucket assigned mechanically from overlap_count: `3→high, 2→med, 1→low`. Initial status = `active`.
./z-harness/plans/z-fix-hypothesis-driven/archive/20260524T061903Z-z-fix-hypothesis-driven/SPEC.md:89:9. **Phase 5 — Compute test order (consensus-first + outlier carve-out, D6).** Sort hypotheses by overlap_count descending. **Always insert** the top 2 unique-to-one-model (overlap=1) hypotheses near the front of the order, even if their prior is `low`. This is the groupthink mitigation.
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:220: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:485:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:542: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:779: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:986:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:1086: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:1480: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:1744:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:1801: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:2038: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:2245:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:2345: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:2995: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:3273:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:3330: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:3695: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:3980:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:4037: ## Phase 5 — Aggregate findings
./z-harness/plans/z-fix-hypothesis-driven/archive/20260524T061903Z-z-fix-hypothesis-driven/TASKS.md:90:- [ ] Phase 4 builds Test Matrix with schema header documented at top of section.
./z-harness/plans/z-fix-hypothesis-driven/archive/20260524T061903Z-z-fix-hypothesis-driven/TASKS.md:91:- [ ] Phase 5 test-order rule: consensus-first + forced outlier carve-out (top 2 overlap=1 rows always tested early).
./research/hermes-agent/website/docs/user-guide/features/kanban.md:417:# Optional: add cross-cutting deps discovered later without re-creating tasks
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:248:-+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:305:- ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:542:- ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:749:-+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:849:- ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:1243:- ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:1507:-+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:1564:- ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:1801:- ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:2008:-+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:2108:- ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:2758:- ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:3036:-+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:3093:- ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:3458:- ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:3743:-+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:3800:- ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:4169:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:4226:+ ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:4463:+ ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:4679:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:4779:+ ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:5173:+ ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:5446:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:5503:+ ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:5740:+ ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:5956:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:6056:+ ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:6706:+ ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:6993:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:7050:+ ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:7415:+ ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:7709:++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:7766:+ ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:8189:++## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:8228:++## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:8709:++## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:8748:++## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:8915:++## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:8954:++## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:9435:++## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:9474:++## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:9642:++## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:9681:++## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:9846:++## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:9885:++## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:10366:++## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:10405:++## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:10573:++## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:10612:++## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:405: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:670:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:727: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:964: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:1171:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:1271: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:1665: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:1929:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:1986: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:2223: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:2430:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:2530: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:3180: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:3458:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:3515: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:3880: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:4165:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:4222: ## Phase 5 — Aggregate findings
./research/hermes-agent/website/docs/user-guide/skills/optional/security/security-oss-forensics.md:310:## Phase 4: Hypothesis Formation
./research/hermes-agent/website/docs/user-guide/skills/optional/security/security-oss-forensics.md:329:## Phase 5: Hypothesis Validation
./research/hermes-agent/website/docs/user-guide/skills/optional/security/security-oss-forensics.md:344:Rejected hypotheses feed back into Phase 4 for refinement (max 3 iterations).
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T009/diff.patch:207:-## Phase 4 — Bundled cross-LLM consult on hypotheses
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T009/diff.patch:242:-## Phase 5 — Isolate (test top hypothesis)
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T009/diff.patch:253:+- `duplicate` critiques: merge `target_id` into `merge_with_id` — union the two rows' `proposed_by` lists (set-union, no duplicates), recompute `overlap_count = len(set(proposed_by))` capped at 3 (the number of unique independent sources from {orchestrator, codex, gemini}), then drop the duplicate row. Never arithmetic-sum the old `overlap_count` values — that can exceed 3, which the Phase 4 `prior` table does not support.
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T009/diff.patch:263:+## Phase 4 — Build the Test Matrix
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T009/diff.patch:290:+## Phase 5 — Compute test order (consensus-first + forced outlier carve-out)
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T009/diff.patch:649:-- `z-harness/<slug>/ISOLATION.md` — Phase 5 (one section per cycle)
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T007/diff-v1.patch:28:+| **Phase 4 — Build Test Matrix** | Append `## Test Matrix`. Prior assigned mechanically: `overlap=3 → high`, `overlap=2 → med`, `overlap=1 → low`. |
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T007/diff-v1.patch:29:+| **Phase 5 — Compute test order** | Sort by `overlap` descending (consensus-first). Force top 2 `overlap=1` hypotheses near the front (outlier carve-out, groupthink mitigation). |
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T007/diff.patch:28:+| **Phase 4 — Build Test Matrix** | Append `## Test Matrix`. Prior assigned mechanically: `overlap=3 → high`, `overlap=2 → med`, `overlap=1 → low`. |
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T007/diff.patch:29:+| **Phase 5 — Compute test order** | Sort by `overlap` descending (consensus-first). Force top 2 `overlap=1` hypotheses near the front (outlier carve-out, groupthink mitigation). |
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:220: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:494:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:551: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:788: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1004:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1104: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1498: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1771:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1828: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2065: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2281:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2381: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3031: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3318:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3375: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3740: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4034:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4091: ## Phase 5 — Aggregate findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4514:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4553:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5034:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5073:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5240:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5279:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5760:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5799:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5967:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6006:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6171:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6210:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6691:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6730:+## Phase 5 — User Gate & Action
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6898:+## Phase 4 — Merge and Synthesize Findings
./z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6937:+## Phase 5 — User Gate & Action
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T006/diff-v1.patch:199:-## Phase 4 — Bundled cross-LLM consult on hypotheses
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T006/diff-v1.patch:252:+## Phase 4 — Build the Test Matrix
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T006/diff-v1.patch:272:+## Phase 5 — Compute test order (consensus-first + forced outlier carve-out)
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T006/diff-v1.patch:341:-## Phase 5 — Isolate (test top hypothesis)
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T006/diff-v1.patch:624:-- `z-harness/<slug>/ISOLATION.md` — Phase 5 (one section per cycle)
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T006/delta-v2.patch:47:++- `duplicate` critiques: merge `target_id` into `merge_with_id` — union the two rows' `proposed_by` lists (set-union, no duplicates), recompute `overlap_count = len(set(proposed_by))` capped at 3 (the number of unique independent sources from {orchestrator, codex, gemini}), then drop the duplicate row. Never arithmetic-sum the old `overlap_count` values — that can exceed 3, which the Phase 4 `prior` table does not support.
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T006/diff.patch:199:-## Phase 4 — Bundled cross-LLM consult on hypotheses
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T006/diff.patch:249:+- `duplicate` critiques: merge `target_id` into `merge_with_id` — union the two rows' `proposed_by` lists (set-union, no duplicates), recompute `overlap_count = len(set(proposed_by))` capped at 3 (the number of unique independent sources from {orchestrator, codex, gemini}), then drop the duplicate row. Never arithmetic-sum the old `overlap_count` values — that can exceed 3, which the Phase 4 `prior` table does not support.
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T006/diff.patch:253:+## Phase 4 — Build the Test Matrix
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T006/diff.patch:273:+## Phase 5 — Compute test order (consensus-first + forced outlier carve-out)
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T006/diff.patch:342:-## Phase 5 — Isolate (test top hypothesis)
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T006/diff.patch:625:-- `z-harness/<slug>/ISOLATION.md` — Phase 5 (one section per cycle)
./research/hermes-agent/website/docs/user-guide/skills/bundled/dogfood/dogfood-dogfood.md:58:   └── report.md          # Final report (generated in Phase 5)
./research/hermes-agent/website/docs/user-guide/skills/bundled/dogfood/dogfood-dogfood.md:130:### Phase 4: Categorize
./research/hermes-agent/website/docs/user-guide/skills/bundled/dogfood/dogfood-dogfood.md:138:### Phase 5: Report
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T004/diff-v1.patch:27:+| **Phase 4 — Synthesize + push back** | For each recommendation, articulate one concrete reason it might be wrong. Surface cross-LLM disagreement to user if present. |
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T004/diff-v1.patch:28:+| **Phase 5 — Approve** | `AskUserQuestion`: approve / modify / abandon. Shortcuts require explicit separate approval. |
./z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:453:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:541:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T004/diff.patch:27:+| **Phase 4 — Synthesize + push back** | For each recommendation, articulate one concrete reason it might be wrong. Surface cross-LLM disagreement to user if present. |
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T004/diff.patch:28:+| **Phase 5 — Approve** | `AskUserQuestion`: approve / modify / abandon. Shortcuts require explicit separate approval. |
./z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:468:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:556:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T003/diff-v1.patch:123:+## Phase 4 — Synthesize + push back
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T003/diff-v1.patch:129:+3. **Flag shortcuts.** If any option is a shortcut over the robust long-lasting solution, mark it explicitly — needs Phase 5 user approval.
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T003/diff-v1.patch:130:+4. **Cross-LLM disagreement.** If Gemini and Codex disagree substantively — or either flags that the proposed cause does NOT explain all symptoms — surface the disagreement to the user in Phase 5. Do not silently pick one side.
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T003/diff-v1.patch:132:+## Phase 5 — Approve
./z-harness/plans/plan-bail-router/archive/tasks/T003/diff.patch:42:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/plan-bail-router/archive/tasks/T003/diff.patch:130:+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T003/diff.patch:123:+## Phase 4 — Synthesize + push back
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T003/diff.patch:129:+3. **Flag shortcuts.** If any option is a shortcut over the robust long-lasting solution, mark it explicitly — needs Phase 5 user approval.
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T003/diff.patch:130:+4. **Cross-LLM disagreement.** If Gemini and Codex disagree substantively — or either flags that the proposed cause does NOT explain all symptoms — surface the disagreement to the user in Phase 5. Do not silently pick one side.
./z-harness/plans/z-fix-hypothesis-driven/archive/tasks/T003/diff.patch:132:+## Phase 5 — Approve
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:751:- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:752:- `skills/z-maintain-docs/SKILL.md:1` — `z-maintain-docs` — Refreshes stale docs. Phase 2 spawns `doc-updater` subagents with `dedup_tags: true`. Phase 3 surfaces stale memories and TAG_COLLISIONS. Phase 4.5 regenerates MEMORIES-FLAT.md after every write. Supports `--apply` and `--audit` flags.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:754:- `skills/z-plan-split/SKILL.md:1` — `z-plan-split` — Pre-emptive scope splitter into 2-6 clusters. Enforces kebab-slug security gate. Phase 4 reconciles file-path overlaps from TASKS.md (canonical) against `FILES_TOUCHED` summary. Writes MANIFEST.md and SHARED-CONCERNS.md. MANIFEST uses stable `cluster_id` (C1…CN) for telemetry and `cluster_slug` for on-disk paths.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:756:- `skills/z-research/SKILL.md:1` — `z-research` — Terrain-mapping pre-plan research. Cost gate at Phase 0 (up to 3 Explores or 1). Phase 4 bundled cross-LLM critique. RESEARCH.md has mandatory `## No-recommendation` section with locked canonical text.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:776:- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:782:  Read `skills/z-amend/SKILL.md` Phase 4 (user gate) and Phase 6 (propagation) for the full checklist.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:863: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:1070: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:766:- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:767:- `skills/z-maintain-docs/SKILL.md:1` — `z-maintain-docs` — Refreshes stale docs. Phase 2 spawns `doc-updater` subagents with `dedup_tags: true`. Phase 3 surfaces stale memories and TAG_COLLISIONS. Phase 4.5 regenerates MEMORIES-FLAT.md after every write. Supports `--apply` and `--audit` flags.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:769:- `skills/z-plan-split/SKILL.md:1` — `z-plan-split` — Pre-emptive scope splitter into 2-6 clusters. Enforces kebab-slug security gate. Phase 4 reconciles file-path overlaps from TASKS.md (canonical) against `FILES_TOUCHED` summary. Writes MANIFEST.md and SHARED-CONCERNS.md. MANIFEST uses stable `cluster_id` (C1…CN) for telemetry and `cluster_slug` for on-disk paths.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:771:- `skills/z-research/SKILL.md:1` — `z-research` — Terrain-mapping pre-plan research. Cost gate at Phase 0 (up to 3 Explores or 1). Phase 4 bundled cross-LLM critique. RESEARCH.md has mandatory `## No-recommendation` section with locked canonical text.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:791:- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:797:  Read `skills/z-amend/SKILL.md` Phase 4 (user gate) and Phase 6 (propagation) for the full checklist.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:878: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:1085: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:1347:    98	## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:1364:   115	## Phase 5 — Codex review (MANDATORY safety gate)
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:1496:   115	## Phase 4 — Synthesize + push back
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:1617:   114	## Phase 4 — Synthesize + push back
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:1623:   120	3. **Flag shortcuts.** If any option is a shortcut over the robust long-lasting solution, mark it explicitly — needs Phase 5 user approval.
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:1724:    99	## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:1741:   116	## Phase 5 — Codex review (MANDATORY safety gate)
./z-harness/plans/plan-bail-router/archive/tasks/T002/diff.patch:75: ## Phase 4 — Implement inline
./z-harness/plans/plan-bail-router/archive/tasks/T002/diff.patch:282: ## Phase 4 — Implement inline
./z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff:327:-## Phase 4 — Bundled cross-LLM consult on hypotheses
./z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff:377:+- `duplicate` critiques: merge `target_id` into `merge_with_id` — union the two rows' `proposed_by` lists (set-union, no duplicates), recompute `overlap_count = len(set(proposed_by))` capped at 3 (the number of unique independent sources from {orchestrator, codex, gemini}), then drop the duplicate row. Never arithmetic-sum the old `overlap_count` values — that can exceed 3, which the Phase 4 `prior` table does not support.
./z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff:381:+## Phase 4 — Build the Test Matrix
./z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff:401:+## Phase 5 — Compute test order (consensus-first + forced outlier carve-out)
./z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff:470:-## Phase 5 — Isolate (test top hypothesis)
./z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff:753:-- `z-harness/<slug>/ISOLATION.md` — Phase 5 (one section per cycle)
./z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff:1253:-## Phase 4 — Bundled cross-LLM consult on hypotheses
./z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff:1288:-## Phase 5 — Isolate (test top hypothesis)
./z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff:1299:+- `duplicate` critiques: merge `target_id` into `merge_with_id` — union the two rows' `proposed_by` lists (set-union, no duplicates), recompute `overlap_count = len(set(proposed_by))` capped at 3 (the number of unique independent sources from {orchestrator, codex, gemini}), then drop the duplicate row. Never arithmetic-sum the old `overlap_count` values — that can exceed 3, which the Phase 4 `prior` table does not support.
./z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff:1309:+## Phase 4 — Build the Test Matrix
./z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff:1336:+## Phase 5 — Compute test order (consensus-first + forced outlier carve-out)
./z-harness/plans/z-fix-hypothesis-driven/archive/20260524T075413Z-review/cumulative.diff:1695:-- `z-harness/<slug>/ISOLATION.md` — Phase 5 (one section per cycle)
./z-harness/plans/lookup-subagent/PLAN.md:57:- Bash + untrusted web data is a meaningful attack surface; verb-blocklist is a model-honored convention, not a runtime guard. **Mitigation:** all Bash commands recorded verbatim in `## Provenance` so the user can audit retroactively. User accepted this risk explicitly in Phase 5.
./z-harness/plans/lookup-subagent/archive/20260524T201705Z-review/shipped.md:19:- **Commands-truncation vs 3 KB cap conflict.** Already user-accepted in Phase 5 (escape via raw-artifact pointer). SPEC could be clearer; deferred.
./z-harness/plans/lookup-subagent/archive/20260524T201705Z-review/findings.md:25:- **[codex]** Commands-truncation conflict: SPEC says `commands:` is verbatim, never truncated, but the 3 KB cap can force truncation. SPEC has an escape via raw-artifact pointer but the rule isn't unambiguous. User already accepted this risk in Phase 5 — SPEC should record that explicitly so future readers don't re-litigate.
./research/hermes-agent/website/docs/user-guide/skills/bundled/software-development/software-development-systematic-debugging.md:228:- Did it work? → Phase 4
./research/hermes-agent/website/docs/user-guide/skills/bundled/software-development/software-development-systematic-debugging.md:241:## Phase 4: Implementation
./research/hermes-agent/website/docs/user-guide/skills/bundled/software-development/software-development-systematic-debugging.md:312:**If 3+ fixes failed:** Question the architecture (Phase 4 step 5).
./z-harness/plans/lookup-subagent/archive/20260524T190609Z-lookup-subagent/PLAN.md:57:- Bash + untrusted web data is a meaningful attack surface; verb-blocklist is a model-honored convention, not a runtime guard. **Mitigation:** all Bash commands recorded verbatim in `## Provenance` so the user can audit retroactively. User accepted this risk explicitly in Phase 5.
./z-harness/plans/lookup-subagent/archive/20260524T190609Z-lookup-subagent/phase3-decisions-final.md:93:## Shortcuts taken (require user approval in Phase 5)
./research/hermes-agent/website/i18n/zh-Hans/docusaurus-plugin-content-docs/current/user-guide/skills/bundled/research/research-research-paper-writing.md:48:│  Phase 2: Experiment     Phase 5: Paper Drafting ◄──┐      │
./research/hermes-agent/website/i18n/zh-Hans/docusaurus-plugin-content-docs/current/user-guide/skills/bundled/research/research-research-paper-writing.md:56:│  Phase 4: Analysis ─────► (feeds back to Phase 2 or 5)     │
./research/hermes-agent/website/i18n/zh-Hans/docusaurus-plugin-content-docs/current/user-guide/skills/bundled/research/research-research-paper-writing.md:2222:  Status: Phase 5 — drafting Methods section.")
./research/hermes-agent/website/docs/user-guide/skills/bundled/research/research-research-paper-writing.md:48:│  Phase 2: Experiment     Phase 5: Paper Drafting ◄──┐      │
./research/hermes-agent/website/docs/user-guide/skills/bundled/research/research-research-paper-writing.md:56:│  Phase 4: Analysis ─────► (feeds back to Phase 2 or 5)     │
./research/hermes-agent/website/docs/user-guide/skills/bundled/research/research-research-paper-writing.md:575:## Phase 4: Result Analysis
./research/hermes-agent/website/docs/user-guide/skills/bundled/research/research-research-paper-writing.md:672:| Core claims supported, results significant | Move to Phase 5 (writing) |
./research/hermes-agent/website/docs/user-guide/skills/bundled/research/research-research-paper-writing.md:675:| Missing one ablation reviewers will ask for | Run it, then Phase 5 |
./research/hermes-agent/website/docs/user-guide/skills/bundled/research/research-research-paper-writing.md:676:| All experiments done but some failed | Note failures, move to Phase 5 |
./research/hermes-agent/website/docs/user-guide/skills/bundled/research/research-research-paper-writing.md:796:## Phase 5: Paper Drafting
./research/hermes-agent/website/docs/user-guide/skills/bundled/research/research-research-paper-writing.md:2146:| **subagent-driven-development** | Phase 5 (Drafting): parallel section writing with 2-stage review (spec compliance then quality) | `skill_view("subagent-driven-development")` |
./research/hermes-agent/website/docs/user-guide/skills/bundled/research/research-research-paper-writing.md:2149:| **diagramming** | Phase 4-5: creating Excalidraw-based figures and architecture diagrams | `skill_view("diagramming")` |
./research/hermes-agent/website/docs/user-guide/skills/bundled/research/research-research-paper-writing.md:2150:| **data-science** | Phase 4 (Analysis): Jupyter live kernel for interactive analysis and visualization | `skill_view("data-science")` |
./research/hermes-agent/website/docs/user-guide/skills/bundled/research/research-research-paper-writing.md:2222:  Status: Phase 5 — drafting Methods section.")
./research/hermes-agent/website/docs/user-guide/skills/bundled/research/research-research-paper-writing.md:2360:| Results are negative/null | See Phase 4.3 on handling negative results. Consider workshops, TMLR, or reframing as analysis. |
./research/hermes-agent/tests/hermes_cli/test_gateway_s6_dispatch.py:1:"""Tests for the Phase 4 s6 dispatch helper in hermes_cli.gateway.
./z-harness/plans/memory-self-improve-loop/SPEC.md:176:In Phase 4 (Recent halts), extend the jq filter to also include `kind == "review_agent_failed"` and `kind == "review_agent_malformed"`. Add a new Phase 4b section called "Recent memory-review activity":
./z-harness/plans/memory-self-improve-loop/PLAN.md:13:- **Failure mode**: soft-skip on agent failure or malformed output. Failure surfaces in a louder push-notify with hint + in `/z-stats` Phase 4 (recent halts). Never blocks the parent command's primary deliverable.
./z-harness/plans/memory-self-improve-loop/PLAN.md:17:- **Telemetry**: new `review_agent_call` event using existing `subagent_model`/`subagent_input_tokens`/`subagent_output_tokens` field names so `/z-stats` Phase 3 picks it up without modification. Phase 4 of `/z-stats` gets an additional jq filter for `review_agent_failed` / `review_agent_malformed`. New Phase 4b lists recent `review_agent_call` events.
./z-harness/plans/memory-self-improve-loop/PLAN.md:48:5. **Telemetry surface in /z-stats** — extend Phase 4 jq filters; add Phase 4b for recent review_agent_call events.
./z-harness/plans/memory-self-improve-loop/TASKS.md:154:## T008 — Extend `commands/z-stats.md` Phase 4 + new Phase 4b
./z-harness/plans/memory-self-improve-loop/TASKS.md:160:**Description:** In Phase 4 (Recent halts), extend the jq filter to also include `kind == "review_agent_failed"` and `kind == "review_agent_malformed"`. Add a new Phase 4b "Recent memory-review activity":
./z-harness/plans/memory-self-improve-loop/TASKS.md:167:- Phase 4 jq filter extended; existing halt-event detection still works.
./z-harness/plans/memory-self-improve-loop/TASKS.md:168:- Phase 4b inserted between Phase 4 and Phase 5.
./z-harness/plans/memory-self-improve-loop/TASKS.md:206:**Description:** Human-tier doc per SPEC.md. Cover: what the agent is, when it fires (end of /z-implement-all and /z-review-all), what user sees (the AskUser prompts), what gets persisted (memory-candidates.jsonl per-run; /z-suggest-memory writes on accept), how to debug a failure (`/z-stats` Phase 4, `events.jsonl` filter for `review_agent_failed`), the v1 limitation (no per-call wall-clock timeout — ctrl-c is the escape).
./z-harness/plans/memory-self-improve-loop/TASKS.md:271:5. `/z-stats` Phase 4b shows the new event.
./research/hermes-agent/tests/hermes_cli/test_profiles_s6_hooks.py:1:"""Tests for the Phase 4 s6 hooks in hermes_cli.profiles.
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:355:+     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:372:+     - Skip Phases 0–3.5. Jump directly to Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:386:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:398:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:402:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:422:+- Continue to Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:424: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:457: ## Phase 5 — Aggregate findings
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:544:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:649: ## Phase 4 — Recent halts
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:659:+## Phase 4b — Recent memory-review activity
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:669: ## Phase 5 — Stalls (post-run gap detection)
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1318:+     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1335:+     - Skip Phases 0–3.5. Jump directly to Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1349:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1361:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1365:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1385:+- Continue to Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1387: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1392: ## Phase 5 — Aggregate findings
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1490:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1596: ## Phase 4 — Recent halts
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1606:+## Phase 4b — Recent memory-review activity
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1616: ## Phase 5 — Stalls (post-run gap detection)
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1636:+- `--from-candidate-json <path>` — path to a JSON file containing a single candidate object (use `-` to read from stdin). When present, Phases 3a–3f are bypassed; the candidate object supplies `type`, `text`, `tags`, and optionally `expires` (via `review_after`). `suggested_concept_slug` is used as `--concept` if `--concept` was not also passed. `evidence_citations` are stored in the memory object's `evidence` field. `candidate_kind` is stored in the memory object's `candidate_kind` field for future analytics but does not affect validation. `rationale` is discarded. Date defaults to today unless `--date` was also passed. Phase 4 validation, Phase 5 atomic write, and Phase 6 MEMORIES-FLAT.md regeneration still run.
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1679:+After mapping, proceed directly to Phase 4 with the assembled fields.
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1711: ## Phase 5 — Write
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1995:+**Step 1 — Run `/z-stats` Phase 4.** Phase 4 (Recent halts) surfaces `review_agent_failed` and `review_agent_malformed` events alongside task-level halts. Phase 4b (Recent memory-review activity) lists recent `review_agent_call` entries with candidate counts and token spend:
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:2036:+- `docs/human/commands.md` — `/z-stats` entry: Phase 4 and Phase 4b telemetry surface.
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/REVIEW-TASKS.md:77:- **Acceptance:** run `/z-amend "Specify --from-candidate-json contract: bypasses /z-suggest-memory Phases 3a-3f, runs Phase 4 (validation) through Phase 6 (MEMORIES-FLAT regen); concept slug is inferred from candidate's suggested_concept_slug field (--concept flag optional); source prefix incident:<RUN_ID> per T009."`; SPEC updated, PLAN unchanged.
./z-harness/plans/brainstorm-and-research/SPEC.md:158:- **Phase 4 (Finalize):** persist user choice; `brainstorm_run_end` event; push-notify.
./z-harness/plans/brainstorm-and-research/SPEC.md:178:- **Phase 4 (Critique):** bundled cross-LLM critique — `MODE: research-review` on both consultants, parallel dispatch.
./z-harness/plans/brainstorm-and-research/SPEC.md:179:- **Phase 5 (Revise):** revise draft; record consultant feedback in `Cross-LLM review notes`; note filled/unfilled gaps.
./z-harness/plans/brainstorm-and-research/TASKS.md:35:    - Phase 4: persist user choice into BRAINSTORM.md; `log-event.sh brainstorm_run_end`; push-notify with next-step recommendation.
./z-harness/plans/brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./z-harness/plans/brainstorm-and-research/TASKS.md:59:    - Phase 5: revise draft based on critiques; record consultant feedback in RESEARCH.md `Cross-LLM review notes` section; note filled/unfilled gaps.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:235:+| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:258:+| `cluster_files_inconsistent` | `/z-plan-split` Phase 4 when `FILES_TOUCHED` ↔ TASKS.md disagree |
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:259:+| `total_cluster_failure` | `/z-plan-split` Phase 3 or Phase 4 when every cluster ends `failed` |
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:260:+| `overlap_detected` | `/z-plan-split` Phase 4 (per overlapping path) |
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:261:+| `overlap_index_rebuilt` | `/z-plan-split` Phase 4 after any post-Phase-3 cluster demotion |
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:354:+You do not call Codex/Gemini consultants (cost discipline — no per-leaf consult in v1). You do not call `Explore` (cost discipline — too expensive for narrow scopes). You DO call `doc-fetcher` iff `docs/llm/INDEX.json` exists in the repo. You DO call `complexity-classifier` in Phase 5.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:375:+  If `RESOLVED_DECISION:` is present, **skip Phases 0-3** and resume from Phase 4 with the resolution baked in. Append the resolution to `archive/<run-id>/decisions.md` under a "Resolved late" section before writing SPEC/PLAN.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:417:+No ancestor is carved out. At dispatch time `/z-plan-split` Phase 5 has not yet written the parent root MANIFEST.md (the root MANIFEST is only written AFTER all cluster-planners return), so any MANIFEST.md visible to this guard indicates the real anti-nesting case: a cluster being planted inside an existing tree (manual nested invocation or a stale prior run). Refuse on the first one found.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:446:+If premise concerns surface, return `STATUS: decision_needed` with a structured payload whose QUESTION is "is this scope coherent?" and AFFECTED_FILES is `[]`. Otherwise write a one-paragraph "premise accepted, here's what I take the goal to be" note into a scratch variable; you will paste it into PLAN.md "Goal" in Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:555:+After escalating one decision, **stop**. Do not proceed to Phase 4. The main thread will resolve the decision and re-spawn you with a `RESOLVED_DECISION:` block; on re-spawn, you skip Phases 0-3 and resume at Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:561:+## Phase 4 — Write SPEC.md + PLAN.md (compressed format)
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:591:+## Phase 5 — Write TASKS.md (with complexity stamping)
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:603:+  - **Complexity:** <stamped in Phase 5 by complexity-classifier>
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:622:+The `FILES_TOUCHED` return field is derived from the union of every task's `**Files:**` line. Keep them honest — the main thread's reconciliation Phase 4 will re-parse TASKS.md and cross-check against `FILES_TOUCHED`; mismatch → `cluster_files_inconsistent` event and the cluster is marked failed.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:732:-- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Codex: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:1034:+- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask the provider: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:1035:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask the provider to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask the provider to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:1179:+- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask the provider: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:1180:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask the provider to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask the provider to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:1571:-- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Gemini: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:2281:+This is the source of truth for "what must NOT change ID or get deleted under our feet." If the amendment requires changing a task that's already `[x]`, you must surface that to the user in Phase 4 — completed work cannot be silently retracted.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:2312:+- Does this change cross any auto-bail threshold (new external dep, public API change, schema change, cross-module)? If yes → flag for consult in Phase 5.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:2319:+## Phase 4 — User gate
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:2323:+- **Approve as drafted** → proceed to Phase 5
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:2334:+## Phase 5 — Optional cross-LLM consult (only if non-obvious)
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:2354:+If neither consult trigger fires, skip this phase entirely — the user already approved in Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:2368:+   - Preserve every `[x]` line untouched unless the user explicitly chose "re-open" in Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:2412:+- **Never skip Phase 4 (user gate).** The user always sees the impact analysis before edits land.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:2457: ## Auto-bail thresholds (check after Phase 4)
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:2692:+   `chosen_framing` is written as `pending` here and updated in Phase 4 to one of `claude | codex | gemini | restart | abandoned` per SPEC.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:2725:+   Do **not** write a `## User choice` section in Phase 3 — Phase 4 writes it for the first time (no placeholder, no duplication).
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:2736:+## Phase 4 — Finalize
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:3006:-## Phase 4 — Bundled cross-LLM consult on hypotheses
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:3053:+- `duplicate` critiques: merge `target_id` into `merge_with_id` — union the two rows' `proposed_by` lists (set-union, no duplicates), recompute `overlap_count = len(set(proposed_by))` capped at 3 (the number of unique independent sources from {orchestrator, codex, gemini}), then drop the duplicate row. Never arithmetic-sum the old `overlap_count` values — that can exceed 3, which the Phase 4 `prior` table does not support.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:3057:+## Phase 4 — Build the Test Matrix
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:3077:+## Phase 5 — Compute test order (consensus-first + forced outlier carve-out)
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:3124:-## Phase 5 — Isolate (test top hypothesis)
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:3430:-- `z-harness/<slug>/ISOLATION.md` — Phase 5 (one section per cycle)
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:3565:+## Phase 4 — Implement inline
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:3583:+## Phase 5 — Codex review (MANDATORY safety gate)
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:3872:+## Phase 4 — Synthesize + push back
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:3878:+3. **Flag shortcuts.** If any option is a shortcut over the robust long-lasting solution, mark it explicitly — needs Phase 5 user approval.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:3879:+4. **Cross-LLM disagreement.** If Gemini and Codex disagree substantively — or either flags that the proposed cause does NOT explain all symptoms — surface the disagreement to the user in Phase 5. Do not silently pick one side.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:3881:+## Phase 5 — Approve
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:4482:+<filled in during Phase 5>
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:4490:+## Phase 4 — (Optional) cross-LLM consult on proposals
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:4507:+## Phase 5 — Discussion with the user
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:4646:+- **Delete** — splice out `memories[index]` from the concept JSON using an atomic write, then log the deletion. MEMORIES-FLAT.md is **NOT** regenerated inline; Phase 4.5 handles regen after all deletes apply.
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:4699:+## Phase 4.5 — Regenerate MEMORIES-FLAT.md
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:4701:+After all accepted concept files have been written in Phase 4, unconditionally regenerate `docs/llm/MEMORIES-FLAT.md` from all current `docs/llm/<slug>.json` files:
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:4709:+If the script exits non-zero, surface the error to the user and halt (do not proceed to Phase 5 with a potentially corrupt MEMORIES-FLAT.md).
./z-harness/plans/memory-self-improve-loop/archive/smoke-test/cumulative.diff:4711: ## Phase 5 — Finalize
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/findings.md:46:- **[gemini] BRAINSTORM restart-flow archived-copy frontmatter mutation is implementation-only.** z-brainstorm Phase 4 sets the archived copy to `status: complete, chosen_framing: restart`. SPEC L165 doesn't mention this mutation. Implementation is correct (otherwise the historical copy would be spec-invalid), but the rule should appear in SPEC.
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/findings.md:58:- **[gemini] `## Cross-LLM review notes` section authorship is implementation-clarified but not spec-clarified.** Tighten SPEC to state "orchestrator writes this section in Phase 5."
./z-harness/plans/memory-self-improve-loop/REVIEW-TASKS.md:77:- **Acceptance:** run `/z-amend "Specify --from-candidate-json contract: bypasses /z-suggest-memory Phases 3a-3f, runs Phase 4 (validation) through Phase 6 (MEMORIES-FLAT regen); concept slug is inferred from candidate's suggested_concept_slug field (--concept flag optional); source prefix incident:<RUN_ID> per T009."`; SPEC updated, PLAN unchanged.
./z-harness/archive/unified-review-tasks/transcripts/001-codex-brainstorm.prompt.md:66:## Phase 5 — Aggregate findings
./z-harness/archive/unified-review-tasks/transcripts/001-codex-brainstorm.prompt.md:89:Phase 4 — User gate: Show amendment.md to the user; approve/revise/abandon. Touched completed tasks get a separate explicit decision.
./z-harness/archive/unified-review-tasks/transcripts/001-codex-brainstorm.prompt.md:98:Phase 5 — Promote to TASKS.md: Only actionable findings go into TASKS.md. An observation with no clear fix stays in REPORT.md.
./z-harness/plans/brainstorm-and-research/archive/tasks/T006/review.prompt.md:64:+| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:235:+| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:258:+| `cluster_files_inconsistent` | `/z-plan-split` Phase 4 when `FILES_TOUCHED` ↔ TASKS.md disagree |
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:259:+| `total_cluster_failure` | `/z-plan-split` Phase 3 or Phase 4 when every cluster ends `failed` |
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:260:+| `overlap_detected` | `/z-plan-split` Phase 4 (per overlapping path) |
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:261:+| `overlap_index_rebuilt` | `/z-plan-split` Phase 4 after any post-Phase-3 cluster demotion |
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:354:+You do not call Codex/Gemini consultants (cost discipline — no per-leaf consult in v1). You do not call `Explore` (cost discipline — too expensive for narrow scopes). You DO call `doc-fetcher` iff `docs/llm/INDEX.json` exists in the repo. You DO call `complexity-classifier` in Phase 5.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:375:+  If `RESOLVED_DECISION:` is present, **skip Phases 0-3** and resume from Phase 4 with the resolution baked in. Append the resolution to `archive/<run-id>/decisions.md` under a "Resolved late" section before writing SPEC/PLAN.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:417:+No ancestor is carved out. At dispatch time `/z-plan-split` Phase 5 has not yet written the parent root MANIFEST.md (the root MANIFEST is only written AFTER all cluster-planners return), so any MANIFEST.md visible to this guard indicates the real anti-nesting case: a cluster being planted inside an existing tree (manual nested invocation or a stale prior run). Refuse on the first one found.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:446:+If premise concerns surface, return `STATUS: decision_needed` with a structured payload whose QUESTION is "is this scope coherent?" and AFFECTED_FILES is `[]`. Otherwise write a one-paragraph "premise accepted, here's what I take the goal to be" note into a scratch variable; you will paste it into PLAN.md "Goal" in Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:555:+After escalating one decision, **stop**. Do not proceed to Phase 4. The main thread will resolve the decision and re-spawn you with a `RESOLVED_DECISION:` block; on re-spawn, you skip Phases 0-3 and resume at Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:561:+## Phase 4 — Write SPEC.md + PLAN.md (compressed format)
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:591:+## Phase 5 — Write TASKS.md (with complexity stamping)
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:603:+  - **Complexity:** <stamped in Phase 5 by complexity-classifier>
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:622:+The `FILES_TOUCHED` return field is derived from the union of every task's `**Files:**` line. Keep them honest — the main thread's reconciliation Phase 4 will re-parse TASKS.md and cross-check against `FILES_TOUCHED`; mismatch → `cluster_files_inconsistent` event and the cluster is marked failed.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:732:-- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Codex: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:1034:+- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask the provider: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:1035:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask the provider to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask the provider to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:1179:+- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask the provider: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:1180:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask the provider to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask the provider to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:1571:-- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Gemini: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:2281:+This is the source of truth for "what must NOT change ID or get deleted under our feet." If the amendment requires changing a task that's already `[x]`, you must surface that to the user in Phase 4 — completed work cannot be silently retracted.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:2312:+- Does this change cross any auto-bail threshold (new external dep, public API change, schema change, cross-module)? If yes → flag for consult in Phase 5.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:2319:+## Phase 4 — User gate
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:2323:+- **Approve as drafted** → proceed to Phase 5
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:2334:+## Phase 5 — Optional cross-LLM consult (only if non-obvious)
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:2354:+If neither consult trigger fires, skip this phase entirely — the user already approved in Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:2368:+   - Preserve every `[x]` line untouched unless the user explicitly chose "re-open" in Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:2412:+- **Never skip Phase 4 (user gate).** The user always sees the impact analysis before edits land.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:2457: ## Auto-bail thresholds (check after Phase 4)
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:2692:+   `chosen_framing` is written as `pending` here and updated in Phase 4 to one of `claude | codex | gemini | restart | abandoned` per SPEC.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:2725:+   Do **not** write a `## User choice` section in Phase 3 — Phase 4 writes it for the first time (no placeholder, no duplication).
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:2736:+## Phase 4 — Finalize
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:3006:-## Phase 4 — Bundled cross-LLM consult on hypotheses
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:3053:+- `duplicate` critiques: merge `target_id` into `merge_with_id` — union the two rows' `proposed_by` lists (set-union, no duplicates), recompute `overlap_count = len(set(proposed_by))` capped at 3 (the number of unique independent sources from {orchestrator, codex, gemini}), then drop the duplicate row. Never arithmetic-sum the old `overlap_count` values — that can exceed 3, which the Phase 4 `prior` table does not support.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:3057:+## Phase 4 — Build the Test Matrix
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:3077:+## Phase 5 — Compute test order (consensus-first + forced outlier carve-out)
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:3124:-## Phase 5 — Isolate (test top hypothesis)
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:3430:-- `z-harness/<slug>/ISOLATION.md` — Phase 5 (one section per cycle)
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:3565:+## Phase 4 — Implement inline
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:3583:+## Phase 5 — Codex review (MANDATORY safety gate)
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:3872:+## Phase 4 — Synthesize + push back
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:3878:+3. **Flag shortcuts.** If any option is a shortcut over the robust long-lasting solution, mark it explicitly — needs Phase 5 user approval.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:3879:+4. **Cross-LLM disagreement.** If Gemini and Codex disagree substantively — or either flags that the proposed cause does NOT explain all symptoms — surface the disagreement to the user in Phase 5. Do not silently pick one side.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:3881:+## Phase 5 — Approve
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:4482:+<filled in during Phase 5>
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:4490:+## Phase 4 — (Optional) cross-LLM consult on proposals
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:4507:+## Phase 5 — Discussion with the user
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:4646:+- **Delete** — splice out `memories[index]` from the concept JSON using an atomic write, then log the deletion. MEMORIES-FLAT.md is **NOT** regenerated inline; Phase 4.5 handles regen after all deletes apply.
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:4699:+## Phase 4.5 — Regenerate MEMORIES-FLAT.md
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:4701:+After all accepted concept files have been written in Phase 4, unconditionally regenerate `docs/llm/MEMORIES-FLAT.md` from all current `docs/llm/<slug>.json` files:
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:4709:+If the script exits non-zero, surface the error to the user and halt (do not proceed to Phase 5 with a potentially corrupt MEMORIES-FLAT.md).
./z-harness/plans/memory-self-improve-loop/archive/test-run-001/cumulative.diff:4711: ## Phase 5 — Finalize
./z-harness/archive/compaction-cadence-plan-critique/transcripts/001-codex-plan-review.prompt.md:26:- New Phase 3.7 between Phase 3.5 (test run) and Phase 4 (consultants)
./z-harness/archive/compaction-cadence-plan-critique/transcripts/001-codex-plan-review.prompt.md:28:- Marker file: `archive/<run>/.pre_consult_acknowledged` — if present on resume, skip Phase 3.7 and jump directly to Phase 4
./z-harness/archive/compaction-cadence-plan-critique/transcripts/001-codex-plan-review.prompt.md:29:- Resume detection: "phase 3.5 artifacts (cumulative.diff, test results) already exist and skips back to Phase 3.7 → Phase 4"
./z-harness/archive/compaction-cadence-plan-critique/transcripts/001-codex-plan-review.prompt.md:37:3. **Marker-file resume scheme in /z-review-all**: The plan says "skip back to Phase 3.7 → Phase 4" on resume if artifacts exist. But Phase 3.7 decides between two options via AskUserQuestion:
./z-harness/plans/brainstorm-and-research/archive/tasks/T006/diff-v1.patch:52:+| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:40:+- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Codex: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:47:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:149:+- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Gemini: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:150:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:422:+   `chosen_framing` is written as `pending` here and updated in Phase 4 to one of `claude | codex | gemini | restart | abandoned` per SPEC.
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:455:+   Do **not** write a `## User choice` section in Phase 3 — Phase 4 writes it for the first time (no placeholder, no duplication).
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:466:+## Phase 4 — Finalize
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:730:+   `chosen_framing` is written as `pending` here and updated in Phase 4 to one of `claude | codex | gemini | restart | abandoned` per SPEC.
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:763:+   Do **not** write a `## User choice` section in Phase 3 — Phase 4 writes it for the first time (no placeholder, no duplication).
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:774:+## Phase 4 — Finalize
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:1049:+## Phase 4 — Bundled cross-LLM critique
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:1071:+2. **If still failed**, record `<consultant>:failed` as a line in Phase 5's `## Cross-LLM review notes` section. The gap that consultant would have filled remains **unfilled**. Log `consultant_failed` with the same shape.
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:1075:+- **At least one consultant succeeded** → proceed to Phase 5 with the available critique; the `status:` frontmatter field may be `complete`.
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:1078:+  - **retry-both** — dispatch Phase 4 from scratch once more.
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:1089:+## Phase 5 — Revise
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:1157:+**`status:` frontmatter rule.** Use `complete` when at least one consultant critique phase succeeded. Use `complete_no_critique` when both consultants failed (after retry) AND the user picked `proceed-with-no-critique` at the Phase 4 aggregate prompt. Never write `status: complete` when both consultants failed.
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:1406:+## Phase 4 — Bundled cross-LLM critique
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:1428:+2. **If still failed**, record `<consultant>:failed` as a line in Phase 5's `## Cross-LLM review notes` section. The gap that consultant would have filled remains **unfilled**. Log `consultant_failed` with the same shape.
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:1432:+- **At least one consultant succeeded** → proceed to Phase 5 with the available critique; the `status:` frontmatter field may be `complete`.
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:1435:+  - **retry-both** — dispatch Phase 4 from scratch once more.
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:1446:+## Phase 5 — Revise
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:1514:+**`status:` frontmatter rule.** Use `complete` when at least one consultant critique phase succeeded. Use `complete_no_critique` when both consultants failed (after retry) AND the user picked `proceed-with-no-critique` at the Phase 4 aggregate prompt. Never write `status: complete` when both consultants failed.
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:1756:+3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:1760:+## Phase 4 — Final clarifications
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:1764:+## Phase 5 — Present + approve
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:2073:+3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:2077:+## Phase 4 — Final clarifications
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:2081:+## Phase 5 — Present + approve
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:2318:+| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff-v1.patch:35:+     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff-v1.patch:52:+     - Skip Phases 0–3.5. Jump directly to Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff-v1.patch:66:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff-v1.patch:78:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff-v1.patch:82:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff-v1.patch:102:+- Continue to Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff-v1.patch:104: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff-v1.patch:137: ## Phase 5 — Aggregate findings
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff-v1.patch:224:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/phase3-decisions-final.md:35:**Verdict:** Soft-skip is right, but the push-notify on failure should be louder: include a literal `"action: check agents/review-agent.md or run /z-stats to see recent review_agent_failed events"` hint. Also: add `/z-stats` Phase 4 entry to surface `review_agent_failed` events alongside other halts. Updating D8.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/phase3-decisions-final.md:52:- **D8 refined:** Soft-skip with explicit hint in push-notify and `/z-stats` Phase 4 surfacing.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/phase3-decisions-final.md:70:Both Gemini and Codex CLIs returned `session_limit` at Phase 3 dispatch (logged: two `consultant_failed` events). Re-running Phase 3 will not work until quotas reset (4pm America/Los_Angeles). User chose to continue; proceeding to Phase 4-6 with orchestrator self-critique as the sole input. SPEC.md / PLAN.md will note this gap explicitly so a future `/z-amend` can re-consult if needed.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/SPEC.md:171:In Phase 4 (Recent halts), extend the jq filter to also include `kind == "review_agent_failed"` and `kind == "review_agent_malformed"`. Add a new Phase 4b section called "Recent memory-review activity":
./z-harness/archive/plan-bail-router/transcripts/001-codex-bundled-decisions.prompt.md:78:- Phase 5 asks user: Amend Plan (Run z-amend), Proceed as-is, or Reject & Re-plan.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff.patch:35:+     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff.patch:52:+     - Skip Phases 0–3.5. Jump directly to Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff.patch:66:+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff.patch:78:+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff.patch:82:+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff.patch:102:+- Continue to Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff.patch:104: ## Phase 4 — Spawn final-review consultants (parallel)
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff.patch:137: ## Phase 5 — Aggregate findings
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff.patch:224:+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/TASKS.md:154:## T008 — Extend `commands/z-stats.md` Phase 4 + new Phase 4b
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/TASKS.md:160:**Description:** In Phase 4 (Recent halts), extend the jq filter to also include `kind == "review_agent_failed"` and `kind == "review_agent_malformed"`. Add a new Phase 4b "Recent memory-review activity":
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/TASKS.md:167:- Phase 4 jq filter extended; existing halt-event detection still works.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/TASKS.md:168:- Phase 4b inserted between Phase 4 and Phase 5.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/TASKS.md:206:**Description:** Human-tier doc per SPEC.md. Cover: what the agent is, when it fires (end of /z-implement-all and /z-review-all), what user sees (the AskUser prompts), what gets persisted (memory-candidates.jsonl per-run; /z-suggest-memory writes on accept), how to debug a failure (`/z-stats` Phase 4, `events.jsonl` filter for `review_agent_failed`), the v1 limitation (no per-call wall-clock timeout — ctrl-c is the escape).
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/TASKS.md:271:5. `/z-stats` Phase 4b shows the new event.
./z-harness/plans/brainstorm-and-research/archive/tasks/T006/review.response.md:79:+| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
./z-harness/plans/brainstorm-and-research/archive/tasks/T006/review.response.md:137:README.md:135:| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
./z-harness/plans/brainstorm-and-research/archive/tasks/T006/review.response.md:815:+| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/PLAN.md:13:- **Failure mode**: soft-skip on agent failure or malformed output. Failure surfaces in a louder push-notify with hint + in `/z-stats` Phase 4 (recent halts). Never blocks the parent command's primary deliverable.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/PLAN.md:17:- **Telemetry**: new `review_agent_call` event using existing `subagent_model`/`subagent_input_tokens`/`subagent_output_tokens` field names so `/z-stats` Phase 3 picks it up without modification. Phase 4 of `/z-stats` gets an additional jq filter for `review_agent_failed` / `review_agent_malformed`. New Phase 4b lists recent `review_agent_call` events.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/PLAN.md:48:5. **Telemetry surface in /z-stats** — extend Phase 4 jq filters; add Phase 4b for recent review_agent_call events.
./z-harness/plans/brainstorm-and-research/archive/tasks/T006/diff.patch:53:+| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
./z-harness/plans/memory-self-improve-loop/archive/tasks/T001/diff.patch:182:+In Phase 4 (Recent halts), extend the jq filter to also include `kind == "review_agent_failed"` and `kind == "review_agent_malformed"`. Add a new Phase 4b section called "Recent memory-review activity":
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.llm.json:57:    "z-review-all Phase 3.7 always runs between Phase 3.5 and Phase 4; it is skipped only when Pre-Phase-0 resume check fast-forwards past it (state file present, HEAD matches, artifact files exist).",
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.llm.json:69:    "z-maintain-docs --audit Phase 2.3 state file (docs/llm/.maintain_docs_audit_state.json) is deleted in Phase 5 cleanup regardless of how the audit ended.",
./z-harness/archive/plan-bail-router/transcripts/001-codex-bundled-decisions.response.md:93:- Phase 5 asks user: Amend Plan (Run z-amend), Proceed as-is, or Reject & Re-plan.
./z-harness/plans/brainstorm-and-research/archive/tasks/T001/review.prompt.md:55:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/commands.human.md:78:Before entering Phase 0, the command checks for a prior state file at `$Z_HARNESS_PLAN_DIR/.review_state.json`. If the file exists, HEAD matches the stored `head_sha`, and the diff artifacts are still on disk, the command fast-forwards directly to Phase 4, skipping the expensive diff-build phases.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/commands.human.md:80:An unconditional Phase 3.7 breakpoint fires before the cross-LLM consultant batch spawns (between Phase 3.5 and Phase 4). No env var gate. An `AskUserQuestion` offers two options: "Pause for /clear" (exit, no state written) or "Proceed now" (write the slug-scoped state file at `$Z_HARNESS_PLAN_DIR/.review_state.json` and continue). On the next invocation, if HEAD matches and the diff file is still present, the command fast-forwards to Phase 4 without re-running Phases 0–3.5. The state file is deleted unconditionally at the end of Phase 6 to ensure subsequent invocations start fresh.
./z-harness/plans/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:39:+- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Codex: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:46:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/memory-self-improve-loop/archive/tasks/T002/diff.patch:30:+- `--from-candidate-json <path>` — path to a JSON file containing a single candidate object (use `-` to read from stdin). When present, Phases 3a–3f are bypassed; the candidate object supplies `type`, `text`, `tags`, and optionally `expires` (via `review_after`). `suggested_concept_slug` is used as `--concept` if `--concept` was not also passed. `evidence_citations` are stored in the memory object's `evidence` field. `candidate_kind` is stored in the memory object's `candidate_kind` field for future analytics but does not affect validation. `rationale` is discarded. Date defaults to today unless `--date` was also passed. Phase 4 validation, Phase 5 atomic write, and Phase 6 MEMORIES-FLAT.md regeneration still run.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T002/diff.patch:73:+After mapping, proceed directly to Phase 4 with the assembled fields.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T002/diff.patch:90: ## Phase 5 — Write
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.human.md:22:- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.human.md:23:- `skills/z-maintain-docs/SKILL.md:1` — `z-maintain-docs` — Refreshes stale docs. Phase 2 spawns `doc-updater` subagents with `dedup_tags: true`. Phase 2.3 fires a pre-audit compaction breakpoint (only when `--audit` is passed), with state file `docs/llm/.maintain_docs_audit_state.json` that fast-forwards re-invocations with the same stale concept set. Phase 3 surfaces stale memories and TAG_COLLISIONS. Phase 4.5 regenerates MEMORIES-FLAT.md after every write. Supports `--apply` and `--audit` flags.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.human.md:25:- `skills/z-plan-split/SKILL.md:1` — `z-plan-split` — Pre-emptive scope splitter into 2-6 clusters. Enforces kebab-slug security gate. Phase 4 reconciles file-path overlaps from TASKS.md (canonical) against `FILES_TOUCHED` summary. Writes MANIFEST.md and SHARED-CONCERNS.md. MANIFEST uses stable `cluster_id` (C1...CN) for telemetry and `cluster_slug` for on-disk paths.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.human.md:27:- `skills/z-research/SKILL.md:1` — `z-research` — Terrain-mapping pre-plan research. Cost gate at Phase 0 (up to 3 Explores or 1). Phase 4 bundled cross-LLM critique. RESEARCH.md has mandatory `## No-recommendation` section with locked canonical text.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.human.md:28:- `skills/z-review-all/SKILL.md:1` — `z-review-all` — Final-gate two-pronged cross-LLM review of cumulative diff. Phase 3.5 runs the full TESTS.md suite across affected modules before consulting LLMs (blocker if any test fails). Phase 3.7 is a mandatory pre-consult compaction breakpoint: always fires between Phase 3.5 and Phase 4, writes `$Z_HARNESS_PLAN_DIR/.review_state.json` when the user picks "proceed now", and the Pre-Phase-0 resume check fast-forwards subsequent invocations past Phases 0-3.5 when HEAD and artifact files are still valid. Promotes findings to REVIEW-TASKS.md.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.human.md:47:- `z-review-all` Phase 3.7 always fires between Phase 3.5 and Phase 4. If the user picks "pause for /clear", no state file is written and Phase 3.7 prompts again on the next invocation. If the user picks "proceed now", `.review_state.json` is written; the Pre-Phase-0 resume check at the next invocation fast-forwards past Phases 0-3.5 when HEAD and both artifact files are still present and match.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.human.md:52:- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.human.md:59:  Read `skills/z-amend/SKILL.md` Phase 4 (user gate) and Phase 6 (propagation) for the full checklist.
./z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.human.md:65:  Check `$Z_HARNESS_PLAN_DIR/.review_state.json` — if it exists with `phase_3_7_acknowledged: true` and HEAD still matches, the skill fast-forwarded to Phase 4.
./z-harness/plans/brainstorm-and-research/archive/tasks/T001/review.response.md:70:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T001/review.response.md:129:- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Codex: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/brainstorm-and-research/archive/tasks/T001/review.response.md:136:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T001/review.response.md:198:agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T001/review.response.md:217:    33	- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Codex: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/brainstorm-and-research/archive/tasks/T001/review.response.md:224:    40	- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T001/review.response.md:322: - **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Codex: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/brainstorm-and-research/archive/tasks/T001/review.response.md:329:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T001/review.response.md:341:agents/gemini-consultant.md:29:- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T001/review.response.md:355:agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/archive/z-uplift-plan-decisions/transcripts/001-codex-plan-decisions.prompt.md:20:- (a) New 'uplift-cross-cutting' agent (Sonnet)
./z-harness/archive/z-uplift-plan-decisions/transcripts/001-codex-plan-decisions.response.md:19:- **D3 broad findings:** Cross-cutting review without a SPEC can be vague. Mitigate by strict classification and optional synthetic `<slug>-cross-cutting/` plan for global work.
./z-harness/archive/z-uplift-plan-decisions/transcripts/001-codex-plan-decisions.response.md:35:From Codex on D3 guidance: "Classify findings as: `global-task` (belongs in dedicated cross-cutting plan), `per-component-context` (inform audits but do not create direct tasks), `risk` (watch item)."
./z-harness/plans/brainstorm-and-research/archive/tasks/T001/diff.patch:39:+- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Codex: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/brainstorm-and-research/archive/tasks/T001/diff.patch:46:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/archive/consults/transcripts/001-gemini-brainstorm.prompt.md:108:## Phase 4 — User gate
./z-harness/archive/consults/transcripts/001-gemini-brainstorm.prompt.md:110:- **Approve as drafted** → proceed to Phase 5
./z-harness/archive/consults/transcripts/001-gemini-brainstorm.prompt.md:124:## Phase 5 — Promote to TASKS.md
./z-harness/archive/20260523-mr-style-reviewer-decisions/transcripts/003-gemini-plan-review.response.md:14:- **Phase 3 before 4 is backwards:** The orchestrator (Phase 4) handles complex data prep: diff generation, byte-size chunking logic, and archive resolution. If you build the agent (Phase 3) first, you are guessing the shape of the chunked diff directory and the archive list format. The orchestrator should be built (or at least stubbed) first to solidify the input contract.
./z-harness/archive/20260523-mr-style-reviewer-decisions/transcripts/003-gemini-plan-review.response.md:17:- **Diff-size heuristic (Phase 4):** The orchestrator is a bash script; it has no tokenizer to enforce `Z_MR_DIFF_CHUNK_TOKENS` (80k). You need a byte-size heuristic (e.g., `80,000 tokens ≈ 320KB`) or a lightweight Python/Node script to handle the chunking natively.
./z-harness/archive/20260523-mr-style-reviewer-decisions/transcripts/003-gemini-plan-review.response.md:18:- **Voice availability pre-check (D14):** How does the system know a voice is missing? If the agent tries and fails, it wastes time and tokens. The orchestrator (Phase 4) should perform a pre-check (e.g., `which codex`) and pass an `available_voices: [claude, gemini]` array to the agent.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.response.md:143:++2. **If still failed**, record `<consultant>:failed` as a line in Phase 5's `## Cross-LLM review notes` section. The gap that consultant would have filled remains **unfilled**. Log `consultant_failed` with the same shape.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.response.md:147:++- **At least one consultant succeeded** → proceed to Phase 5 with the available critique; the `status:` frontmatter field may be `complete`.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.response.md:150:++  - **retry-both** — dispatch Phase 4 from scratch once more.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.response.md:161: +## Phase 5 — Revise
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.response.md:187:++**`status:` frontmatter rule.** Use `complete` when at least one consultant critique phase succeeded. Use `complete_no_critique` when both consultants failed (after retry) AND the user picked `proceed-with-no-critique` at the Phase 4 aggregate prompt. Never write `status: complete` when both consultants failed.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.response.md:311:++2. **If still failed**, record `<consultant>:failed` as a line in Phase 5's `## Cross-LLM review notes` section. The gap that consultant would have filled remains **unfilled**. Log `consultant_failed` with the same shape.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.response.md:315:++- **At least one consultant succeeded** → proceed to Phase 5 with the available critique; the `status:` frontmatter field may be `complete`.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.response.md:318:++  - **retry-both** — dispatch Phase 4 from scratch once more.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.response.md:329: +## Phase 5 — Revise
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.response.md:355:++**`status:` frontmatter rule.** Use `complete` when at least one consultant critique phase succeeded. Use `complete_no_critique` when both consultants failed (after retry) AND the user picked `proceed-with-no-critique` at the Phase 4 aggregate prompt. Never write `status: complete` when both consultants failed.
./z-harness/archive/20260525T000302Z-compaction-cadence/transcripts/001-gemini-bundled-decisions.response.md:7:### D3: Breakpoint in `/z-review-all` before Phase 4?
./z-harness/archive/20260525T000302Z-compaction-cadence/transcripts/001-gemini-bundled-decisions.response.md:11:*   **Missed Consideration:** The pause might feel annoying if the user *just* cleared context. To mitigate, frame the prompt as a strong recommendation rather than a hard blocker: *"Ready for Phase 4. Highly recommend /clear before continuing if you haven't recently."*
./z-harness/archive/consults/transcripts/003-gemini-brainstorm.prompt.md:108:## Phase 4 — User gate
./z-harness/archive/consults/transcripts/003-gemini-brainstorm.prompt.md:110:- **Approve as drafted** → proceed to Phase 5
./z-harness/archive/consults/transcripts/003-gemini-brainstorm.prompt.md:124:## Phase 5 — Promote to TASKS.md
./z-harness/archive/20260525T000302Z-compaction-cadence/transcripts/001-gemini-bundled-decisions.prompt.md:18:### D3. Add breakpoint in /z-review-all before Phase 4 (cumulative-diff consultant spawn — heaviest single context burn)?
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.prompt.md:38:- Phase 4 (Critique): bundled cross-LLM critique — MODE: research-review on both consultants, parallel dispatch.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.prompt.md:39:- Phase 5 (Revise): revise; record consultant feedback in Cross-LLM review notes; note filled/unfilled.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.prompt.md:52:  - Phase 4: bundled MODE: research-review on BOTH consultants in parallel.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.prompt.md:53:  - Phase 5: record consultant feedback in `## Cross-LLM review notes`, filled vs unfilled.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.prompt.md:247:+## Phase 4 — Bundled cross-LLM critique
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.prompt.md:268:+## Phase 5 — Revise
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.prompt.md:542:+## Phase 4 — Bundled cross-LLM critique
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.prompt.md:563:+## Phase 5 — Revise
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.human.diff:28:-- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.human.diff:29:-- `skills/z-maintain-docs/SKILL.md:1` — `z-maintain-docs` — Refreshes stale docs. Phase 2 spawns `doc-updater` subagents with `dedup_tags: true`. Phase 3 surfaces stale memories and TAG_COLLISIONS. Phase 4.5 regenerates MEMORIES-FLAT.md after every write. Supports `--apply` and `--audit` flags.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.human.diff:31:-- `skills/z-plan-split/SKILL.md:1` — `z-plan-split` — Pre-emptive scope splitter into 2-6 clusters. Enforces kebab-slug security gate. Phase 4 reconciles file-path overlaps from TASKS.md (canonical) against `FILES_TOUCHED` summary. Writes MANIFEST.md and SHARED-CONCERNS.md. MANIFEST uses stable `cluster_id` (C1…CN) for telemetry and `cluster_slug` for on-disk paths.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.human.diff:33:-- `skills/z-research/SKILL.md:1` — `z-research` — Terrain-mapping pre-plan research. Cost gate at Phase 0 (up to 3 Explores or 1). Phase 4 bundled cross-LLM critique. RESEARCH.md has mandatory `## No-recommendation` section with locked canonical text.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.human.diff:77:-- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.human.diff:92:-  Read `skills/z-amend/SKILL.md` Phase 4 (user gate) and Phase 6 (propagation) for the full checklist.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/diff-v1.patch:186:+## Phase 4 — Bundled cross-LLM critique
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/diff-v1.patch:207:+## Phase 5 — Revise
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/diff-v1.patch:481:+## Phase 4 — Bundled cross-LLM critique
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/diff-v1.patch:502:+## Phase 5 — Revise
./z-harness/archive/tasks/T007/review.prompt.md:16:4. Phase 5: Three mutually-exclusive modes (append, edit, delete) with atomic writes
./z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/commands.human.diff:109:-An unconditional breakpoint fires before the cross-LLM consultant batch spawns (between Phase 3.5 and Phase 4). No env var gate. An `AskUserQuestion` offers two options: "Pause for /clear" (exit, no state written) or "Proceed now" (write slug-scoped `.review_state.json` at `z-harness/plans/<slug>/.review_state.json` and continue). On the next invocation, if HEAD matches and the diff file is still present, the command fast-forwards to Phase 4 without re-running the expensive earlier phases.
./z-harness/archive/tasks/T007/review.response.md:11:- **Phase 4 (Validate):** Complete validation table with all error messages.
./z-harness/archive/tasks/T007/review.response.md:12:- **Phase 5 (Write):** Append mode shows full atomic-write Python code (tmpfile + fsync + os.replace). Edit and Delete modes correctly reference "same pattern as append" (matching spec structure). All three modes documented as mutually exclusive.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/delta-v2.patch:114:++2. **If still failed**, record `<consultant>:failed` as a line in Phase 5's `## Cross-LLM review notes` section. The gap that consultant would have filled remains **unfilled**. Log `consultant_failed` with the same shape.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/delta-v2.patch:118:++- **At least one consultant succeeded** → proceed to Phase 5 with the available critique; the `status:` frontmatter field may be `complete`.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/delta-v2.patch:121:++  - **retry-both** — dispatch Phase 4 from scratch once more.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/delta-v2.patch:132: +## Phase 5 — Revise
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/delta-v2.patch:158:++**`status:` frontmatter rule.** Use `complete` when at least one consultant critique phase succeeded. Use `complete_no_critique` when both consultants failed (after retry) AND the user picked `proceed-with-no-critique` at the Phase 4 aggregate prompt. Never write `status: complete` when both consultants failed.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/delta-v2.patch:282:++2. **If still failed**, record `<consultant>:failed` as a line in Phase 5's `## Cross-LLM review notes` section. The gap that consultant would have filled remains **unfilled**. Log `consultant_failed` with the same shape.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/delta-v2.patch:286:++- **At least one consultant succeeded** → proceed to Phase 5 with the available critique; the `status:` frontmatter field may be `complete`.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/delta-v2.patch:289:++  - **retry-both** — dispatch Phase 4 from scratch once more.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/delta-v2.patch:300: +## Phase 5 — Revise
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/delta-v2.patch:326:++**`status:` frontmatter rule.** Use `complete` when at least one consultant critique phase succeeded. Use `complete_no_critique` when both consultants failed (after retry) AND the user picked `proceed-with-no-critique` at the Phase 4 aggregate prompt. Never write `status: complete` when both consultants failed.
./z-harness/archive/20260524T061903Z-z-fix-hypothesis-driven/transcripts/001-gemini-bundled-decisions.prompt.md:44:  3. Reuse existing `debug-hypotheses` mode (currently shaped for Phase 4 of /z-debug; would need extension)
./z-harness/archive/20260524T061903Z-z-fix-hypothesis-driven/transcripts/001-gemini-bundled-decisions.prompt.md:61:### /z-debug Phase 4 (current cross-LLM consult for hypotheses):
./z-harness/archive/20260524T061903Z-z-fix-hypothesis-driven/transcripts/001-gemini-bundled-decisions.prompt.md:130:- ISOLATION.md cycles are capped at 3 (per /z-debug Phase 5); a MATRIX.md appended per cycle may be verbose if all 3 cycles run.
./z-harness/archive/tasks/T006/review.prompt.md:1633:## Phase 4 — Merge and Synthesize Findings
./z-harness/archive/tasks/T006/review.prompt.md:1672:## Phase 5 — User Gate & Action
./z-harness/archive/tasks/T006/review.prompt.md:1836:## Phase 4 — Merge and Synthesize Findings
./z-harness/archive/tasks/T006/review.prompt.md:1875:## Phase 5 — User Gate & Action
./z-harness/archive/tasks/T006/review.prompt.md:2347:## Phase 4 — Merge and Synthesize Findings
./z-harness/archive/tasks/T006/review.prompt.md:2386:## Phase 5 — User Gate & Action
./z-harness/archive/consultant-review/transcripts/001-gemini-plan-review.prompt.md:26:- Resume: "write a marker file archive/<run>/.pre_consult_acknowledged when user chooses (b); presence of this marker on resume means 'Phase 3.7 already decided, skip directly to Phase 4'."
./z-harness/archive/compaction-cadence/transcripts/001-codex-light-fix.response.md:23:Worth the UX friction. Phase 4 is a known context spike: two consultants each reading `SPEC.md`, `PLAN.md`, `TASKS.md`, `cumulative.diff`, and `docs/llm/*.json`. If `cumulative.diff` is huge, this is exactly where quality collapses.
./z-harness/archive/compaction-cadence/transcripts/001-codex-light-fix.response.md:36:Review is about to spawn high-context consultants. Run /clear or /compact first, then re-invoke /z-review-all to resume Phase 4.
./z-harness/archive/compaction-cadence/transcripts/001-codex-light-fix.prompt.md:33:## D3. Add breakpoint in /z-review-all before Phase 4?
./z-harness/archive/compaction-cadence/transcripts/001-codex-light-fix.prompt.md:35:Phase 4 (consultant spawn) is **the heaviest single context burn** in the harness:
./z-harness/archive/compaction-cadence/transcripts/001-codex-light-fix.prompt.md:42:(a) **Yes** — pre-Phase-4 push notification: "About to spawn consultants; `/compact` first if needed, then re-invoke `/z-review-all` to resume from Phase 4."  
./z-harness/archive/tasks/T006/review/review.prompt.md:15:8. Phase 4 — Test Matrix with schema header documented; prior from overlap mechanical (3→high, 2→med, 1→low)
./z-harness/archive/tasks/T006/review/review.prompt.md:16:9. Phase 5 — consensus-first ranking + forced outlier carve-out (top 2 overlap=1 rows near front)
./z-harness/archive/tasks/T006/review/review.prompt.md:36:- Phase 4 Test Matrix schema header documented at top of section
./z-harness/archive/tasks/T006/review/review.prompt.md:37:- Phase 5 consensus-first + forced outlier carve-out (top 2 overlap=1 tested early)
./z-harness/archive/tasks/T006/review/review.prompt.md:244:-## Phase 4 — Bundled cross-LLM consult on hypotheses
./z-harness/archive/tasks/T006/review/review.prompt.md:299:+## Phase 4 — Build the Test Matrix
./z-harness/archive/tasks/T006/review/review.prompt.md:319:+## Phase 5 — Compute test order (consensus-first + forced outlier carve-out)
./z-harness/archive/tasks/T006/review/review.prompt.md:388:-## Phase 5 — Isolate (test top hypothesis)
./z-harness/archive/tasks/T006/review/review.prompt.md:671:-- `z-harness/<slug>/ISOLATION.md` — Phase 5 (one section per cycle)
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:53:- Phase 4 (Critique): bundled cross-LLM critique — MODE: research-review on both consultants, parallel dispatch.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:54:- Phase 5 (Revise): revise; record consultant feedback in Cross-LLM review notes; note filled/unfilled.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:67:  - Phase 4: bundled MODE: research-review on BOTH consultants in parallel.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:68:  - Phase 5: record consultant feedback in `## Cross-LLM review notes`, filled vs unfilled.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:262:+## Phase 4 — Bundled cross-LLM critique
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:283:+## Phase 5 — Revise
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:557:+## Phase 4 — Bundled cross-LLM critique
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:578:+## Phase 5 — Revise
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:914:   <filled in Phase 4>
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:926:## Phase 4 — Finalize
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1094:./agents/gemini-consultant.md:29:- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1099:./agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1163:./brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1186:./z-harness/brainstorm-and-research/SPEC.md:178:- **Phase 4 (Critique):** bundled cross-LLM critique — `MODE: research-review` on both consultants, parallel dispatch.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1213:./brainstorm-and-research/SPEC.md:242:**Phase 4 — Bundled cross-LLM critique** (`MODE: research-review` on both consultants):
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1218:./brainstorm-and-research/SPEC.md:266:**`MODE: research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + the question + the doc-fetcher synthesis. Critique for: (1) missing findings — claims that the codebase supports but the draft didn't make; (2) wrong claims — assertions contradicted by the cited source files; (3) undocumented constraints — limits the draft should have noted; (4) hypothesis creep — anywhere the draft snuck in a recommendation despite the "no-recommendation" rule. **Do not recommend an approach yourself.** Return: gaps to fill, errors to correct, no recommendation.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1311:./z-harness/brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1370:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1393:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:242:**Phase 4 — Bundled cross-LLM critique** (`MODE: research-review` on both consultants):
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1398:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:266:**`MODE: research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + the question + the doc-fetcher synthesis. Critique for: (1) missing findings — claims that the codebase supports but the draft didn't make; (2) wrong claims — assertions contradicted by the cited source files; (3) undocumented constraints — limits the draft should have noted; (4) hypothesis creep — anywhere the draft snuck in a recommendation despite the "no-recommendation" rule. **Do not recommend an approach yourself.** Return: gaps to fill, errors to correct, no recommendation.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1498:./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:55:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1513:./z-harness/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:46:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1522:./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:59:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1598:./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:46:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1614:./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:74:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1662:./z-harness/brainstorm-and-research/archive/tasks/T002/diff.patch:35:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1683:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:70:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1688:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:136:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1691:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:198:agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1698:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:224:    40	- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1707:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:329:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1709:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:341:agents/gemini-consultant.md:29:- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1715:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:355:agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1947:    58	    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:1948:    59	    - Phase 5: revise draft based on critiques; record consultant feedback in RESEARCH.md `Cross-LLM review notes` section; note filled/unfilled gaps.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:2193:   116	**Author's response:** <which gaps were filled in Phase 4, which were intentionally left, why>
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:2266:   189	**Phase 4 — Finalize**:
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:2319:   242	**Phase 4 — Bundled cross-LLM critique** (`MODE: research-review` on both consultants):
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:2322:   245	**Phase 5 — Revise draft based on critiques**:
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:2519:   180	## Phase 4 — Bundled cross-LLM critique
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review.response.md:2540:   201	## Phase 5 — Revise
./z-harness/archive/tasks/T006/review/review.response.md:5:2. [commands/z-debug.md:214](</Users/zeke/dev/z-harness/commands/z-debug.md:214>) - Duplicate critique handling says to “sum `overlap_count`”. That can produce impossible values above 3, while Phase 4 defines overlap as `1-3` and maps only `3→high, 2→med, 1→low` at [commands/z-debug.md:225](</Users/zeke/dev/z-harness/commands/z-debug.md:225>). Merge should recompute `overlap_count` from the union of unique `proposed_by` models, capped by the three Round-1 sources, rather than blindly summing.
./z-harness/archive/portable-harness-plan-review/transcripts/001-plan-review-portable-harness.prompt.md:31:Phase 4: Discovery + /z-providers-discover command.
./z-harness/archive/portable-harness-plan-review/transcripts/001-plan-review-portable-harness.prompt.md:32:Phase 5: Consultant + reviewer rewrite (canonical agents, delete legacy, sweep dispatch sites).
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.prompt.md:128:++2. **If still failed**, record `<consultant>:failed` as a line in Phase 5's `## Cross-LLM review notes` section. The gap that consultant would have filled remains **unfilled**. Log `consultant_failed` with the same shape.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.prompt.md:132:++- **At least one consultant succeeded** → proceed to Phase 5 with the available critique; the `status:` frontmatter field may be `complete`.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.prompt.md:135:++  - **retry-both** — dispatch Phase 4 from scratch once more.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.prompt.md:146: +## Phase 5 — Revise
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.prompt.md:172:++**`status:` frontmatter rule.** Use `complete` when at least one consultant critique phase succeeded. Use `complete_no_critique` when both consultants failed (after retry) AND the user picked `proceed-with-no-critique` at the Phase 4 aggregate prompt. Never write `status: complete` when both consultants failed.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.prompt.md:296:++2. **If still failed**, record `<consultant>:failed` as a line in Phase 5's `## Cross-LLM review notes` section. The gap that consultant would have filled remains **unfilled**. Log `consultant_failed` with the same shape.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.prompt.md:300:++- **At least one consultant succeeded** → proceed to Phase 5 with the available critique; the `status:` frontmatter field may be `complete`.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.prompt.md:303:++  - **retry-both** — dispatch Phase 4 from scratch once more.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.prompt.md:314: +## Phase 5 — Revise
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/review-v2.prompt.md:340:++**`status:` frontmatter rule.** Use `complete` when at least one consultant critique phase succeeded. Use `complete_no_critique` when both consultants failed (after retry) AND the user picked `proceed-with-no-critique` at the Phase 4 aggregate prompt. Never write `status: complete` when both consultants failed.
./z-harness/archive/mr-style-reviewer-plan-review/transcripts/001-codex-plan-review.response.md:33:10. **Phase 3/5 boundary:** Clarify that Phase 3 output is internal milestone; Phase 5 must preserve MR-REVIEW.md output contract and add voice tags + consensus tier-bump to each finding.
./z-harness/archive/portable-harness-plan-review/transcripts/001-plan-review-portable-harness.response.md:4:- Legacy Removal: SPEC lists "legacy removal in this plan" as a non-goal (line 198), but PLAN Phase 5 says "delete legacy" and context notes "legacy agent shims are ripped" is locked. SPEC non-goals must be updated to remove this contradiction.
./z-harness/archive/portable-harness-plan-review/transcripts/001-plan-review-portable-harness.response.md:7:- Discovery script language drift: SPEC appears to imply Python (`discover-providers.sh` as deterministic shell, line 108), but PLAN Phase 4 & D7 are clear on shell. Verify SPEC doesn't mention Python elsewhere for discovery.
./z-harness/archive/portable-harness-plan-review/transcripts/001-plan-review-portable-harness.response.md:10:- Phase 6 (Agy Research) happens too late: Researching target IDE schemas (Agy) in Phase 6 *after* locking in the canonical agent rewrites in Phase 5 risks rework. If Agy requires specific prompt boundaries or metadata, Phase 5 will need to be redone. Move P6 *before* P5.
./z-harness/archive/portable-harness-plan-review/transcripts/001-plan-review-portable-harness.response.md:13:- Double-touching files (Phase 2 & Phase 5): Phase 2 sweeps all commands to update path logic. Phase 5 sweeps all commands *again* to update agent dispatch names. Combine sweeps to modify command files once.
./z-harness/archive/portable-harness-plan-review/transcripts/001-plan-review-portable-harness.response.md:19:- Role Fallback Logic (Phase 5): SPEC lists "unbound roles" as an edge case (line 185). If `consultant-secondary.md` is requested but no secondary provider is configured, does the dispatch fail-fast or fallback to primary? PLAN Phase 5 needs an explicit fallback strategy.
./z-harness/archive/portable-harness-plan-review/transcripts/001-plan-review-portable-harness.response.md:20:- In-flight `TASKS.md` crash: While `migrate-plan-layout.sh` migrates directories, deleting legacy agent files immediately (Phase 5) will hard-fail if in-flight plans' `TASKS.md` explicitly instruct calling `codex-consultant` or `gemini-consultant`. Need a grace period or explicit per-TASKS-version note.
./z-harness/archive/portable-harness-plan-review/transcripts/001-plan-review-portable-harness.response.md:22:- Dual-read scope (Phase 1 vs Phase 5): If legacy shims are ripped (P5), but dual-read fallback is kept for paths (P1), ensure dual-read logic explicitly *only* applies to plan data directories, not agent execution paths, to avoid masking "missing agent" errors.
./z-harness/archive/portable-harness-plan-review/transcripts/001-plan-review-portable-harness.response.md:35:1. Move Phase 6 (agy research) *before* Phase 5 (consultant rewrites).
./z-harness/archive/portable-harness-plan-review/transcripts/001-plan-review-portable-harness.response.md:36:2. Combine Phase 2 + Phase 5 sweeps to avoid double-touching command files.
./z-harness/archive/portable-harness-plan-review/transcripts/001-plan-review-portable-harness.response.md:42:8. Clarify Phase 5 fallback strategy for unbound secondary provider.
./z-harness/archive/tasks/T006/review.response.md:1648:## Phase 4 — Merge and Synthesize Findings
./z-harness/archive/tasks/T006/review.response.md:1687:## Phase 5 — User Gate & Action
./z-harness/archive/tasks/T006/review.response.md:1851:## Phase 4 — Merge and Synthesize Findings
./z-harness/archive/tasks/T006/review.response.md:1890:## Phase 5 — User Gate & Action
./z-harness/archive/tasks/T006/review.response.md:2362:## Phase 4 — Merge and Synthesize Findings
./z-harness/archive/tasks/T006/review.response.md:2401:## Phase 5 — User Gate & Action
./z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.human.md:21:- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
./z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.human.md:22:- `skills/z-maintain-docs/SKILL.md:1` — `z-maintain-docs` — Refreshes stale docs. Phase 2 spawns `doc-updater` subagents with `dedup_tags: true`. Phase 3 surfaces stale memories and TAG_COLLISIONS. Phase 4.5 regenerates MEMORIES-FLAT.md after every write. Supports `--apply` and `--audit` flags.
./z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.human.md:24:- `skills/z-plan-split/SKILL.md:1` — `z-plan-split` — Pre-emptive scope splitter into 2-6 clusters. Enforces kebab-slug security gate. Phase 4 reconciles file-path overlaps from TASKS.md (canonical) against `FILES_TOUCHED` summary. Writes MANIFEST.md and SHARED-CONCERNS.md. MANIFEST uses stable `cluster_id` (C1…CN) for telemetry and `cluster_slug` for on-disk paths.
./z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.human.md:26:- `skills/z-research/SKILL.md:1` — `z-research` — Terrain-mapping pre-plan research. Cost gate at Phase 0 (up to 3 Explores or 1). Phase 4 bundled cross-LLM critique. RESEARCH.md has mandatory `## No-recommendation` section with locked canonical text.
./z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.human.md:46:- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
./z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.human.md:52:  Read `skills/z-amend/SKILL.md` Phase 4 (user gate) and Phase 6 (propagation) for the full checklist.
./z-harness/archive/mr-style-reviewer-plan-review/transcripts/001-codex-plan-review.prompt.md:11:5. **Phase ordering** — Phase 3 (Claude-only) outputs get replaced in Phase 5 (multi-voice). Is that the intended workflow?
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/diff.patch:221:+## Phase 4 — Bundled cross-LLM critique
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/diff.patch:243:+2. **If still failed**, record `<consultant>:failed` as a line in Phase 5's `## Cross-LLM review notes` section. The gap that consultant would have filled remains **unfilled**. Log `consultant_failed` with the same shape.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/diff.patch:247:+- **At least one consultant succeeded** → proceed to Phase 5 with the available critique; the `status:` frontmatter field may be `complete`.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/diff.patch:250:+  - **retry-both** — dispatch Phase 4 from scratch once more.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/diff.patch:261:+## Phase 5 — Revise
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/diff.patch:329:+**`status:` frontmatter rule.** Use `complete` when at least one consultant critique phase succeeded. Use `complete_no_critique` when both consultants failed (after retry) AND the user picked `proceed-with-no-critique` at the Phase 4 aggregate prompt. Never write `status: complete` when both consultants failed.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/diff.patch:577:+## Phase 4 — Bundled cross-LLM critique
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/diff.patch:599:+2. **If still failed**, record `<consultant>:failed` as a line in Phase 5's `## Cross-LLM review notes` section. The gap that consultant would have filled remains **unfilled**. Log `consultant_failed` with the same shape.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/diff.patch:603:+- **At least one consultant succeeded** → proceed to Phase 5 with the available critique; the `status:` frontmatter field may be `complete`.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/diff.patch:606:+  - **retry-both** — dispatch Phase 4 from scratch once more.
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/diff.patch:617:+## Phase 5 — Revise
./z-harness/plans/brainstorm-and-research/archive/tasks/T004/diff.patch:685:+**`status:` frontmatter rule.** Use `complete` when at least one consultant critique phase succeeded. Use `complete_no_critique` when both consultants failed (after retry) AND the user picked `proceed-with-no-critique` at the Phase 4 aggregate prompt. Never write `status: complete` when both consultants failed.
./z-harness/archive/tasks/T001/review-v2.response.md:37:   - --cross-cutting=skip (line 27)
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/review.prompt.md:253:+3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/review.prompt.md:257:+## Phase 4 — Final clarifications
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/review.prompt.md:261:+## Phase 5 — Present + approve
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/review.prompt.md:564:+3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/review.prompt.md:568:+## Phase 4 — Final clarifications
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/review.prompt.md:572:+## Phase 5 — Present + approve
./z-harness/plans/brainstorm-and-research/archive/tasks/T100/diff.patch:8: - **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Gemini: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/brainstorm-and-research/archive/tasks/T100/diff.patch:9:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/review.response.md:268:+3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/review.response.md:272:+## Phase 4 — Final clarifications
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/review.response.md:276:+## Phase 5 — Present + approve
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/review.response.md:579:+3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/review.response.md:583:+## Phase 4 — Final clarifications
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/review.response.md:587:+## Phase 5 — Present + approve
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/diff.patch:214:+3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/diff.patch:218:+## Phase 4 — Final clarifications
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/diff.patch:222:+## Phase 5 — Present + approve
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/diff.patch:530:+3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/diff.patch:534:+## Phase 4 — Final clarifications
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/diff.patch:538:+## Phase 5 — Present + approve
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.prompt.md:23:- Phase 4: persist chosen_framing; brainstorm_run_end; push-notify.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.prompt.md:262:+   <filled in Phase 4>
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.prompt.md:274:+## Phase 4 — Finalize
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.prompt.md:556:+   <filled in Phase 4>
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.prompt.md:568:+## Phase 4 — Finalize
./z-harness/plans/brainstorm-and-research/archive/tasks/T002/review.prompt.md:58:+- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Gemini: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/brainstorm-and-research/archive/tasks/T002/review.prompt.md:59:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/archive/tasks/T001/review-v2.prompt.md:23:- contains all 7 CLI flags: --components=, --component, --retry-bailed, --refresh-component, --dimensions=, --cross-cutting=, --no-style ✓
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:209:+3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:213:+## Phase 4 — Final clarifications
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:217:+## Phase 5 — Present + approve
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:520:+3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:524:+## Phase 4 — Final clarifications
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:528:+## Phase 5 — Present + approve
./z-harness/plans/brainstorm-and-research/archive/tasks/T002/review.response.md:73:+- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Gemini: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/brainstorm-and-research/archive/tasks/T002/review.response.md:74:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/delta-v2.patch:104:++   `chosen_framing` is written as `pending` here and updated in Phase 4 to one of `claude | codex | gemini | restart | abandoned` per SPEC.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/delta-v2.patch:115:-+   <filled in Phase 4>
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/delta-v2.patch:118:++   Do **not** write a `## User choice` section in Phase 3 — Phase 4 writes it for the first time (no placeholder, no duplication).
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/delta-v2.patch:249:++   `chosen_framing` is written as `pending` here and updated in Phase 4 to one of `claude | codex | gemini | restart | abandoned` per SPEC.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/delta-v2.patch:260:-+   <filled in Phase 4>
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/delta-v2.patch:263:++   Do **not** write a `## User choice` section in Phase 3 — Phase 4 writes it for the first time (no placeholder, no duplication).
./z-harness/plans/brainstorm-and-research/archive/tasks/T002/diff.patch:34:+- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Gemini: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/brainstorm-and-research/archive/tasks/T002/diff.patch:35:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/diff-v1.patch:229:+   <filled in Phase 4>
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/diff-v1.patch:241:+## Phase 4 — Finalize
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/diff-v1.patch:523:+   <filled in Phase 4>
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/diff-v1.patch:535:+## Phase 4 — Finalize
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/diff.patch:210:+   `chosen_framing` is written as `pending` here and updated in Phase 4 to one of `claude | codex | gemini | restart | abandoned` per SPEC.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/diff.patch:243:+   Do **not** write a `## User choice` section in Phase 3 — Phase 4 writes it for the first time (no placeholder, no duplication).
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/diff.patch:254:+## Phase 4 — Finalize
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/diff.patch:517:+   `chosen_framing` is written as `pending` here and updated in Phase 4 to one of `claude | codex | gemini | restart | abandoned` per SPEC.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/diff.patch:550:+   Do **not** write a `## User choice` section in Phase 3 — Phase 4 writes it for the first time (no placeholder, no duplication).
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/diff.patch:561:+## Phase 4 — Finalize
./z-harness/archive/20260524T203829Z-subagent-liveness/transcripts/003-gemini-plan-review.response.md:16:**Issue:** The context notes that `commands/z-audit-plan.md` exists but is missing from `docs/llm/commands.json`. The plan's Phase 4 generically mentions "docs/memory and z-audit-plan drift" but fails to explicitly address the registry file.
./z-harness/archive/20260524T203829Z-subagent-liveness/transcripts/003-gemini-plan-review.response.md:17:**Fix:** Update Phase 4 to explicitly add `z-audit-plan.md` to the `docs/llm/commands.json` registry. If this isn't fixed, the export generation (Phase 5) will continue to omit the command from IDE exports.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:38:- Phase 4: persist chosen_framing; brainstorm_run_end; push-notify.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:277:+   <filled in Phase 4>
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:289:+## Phase 4 — Finalize
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:571:+   <filled in Phase 4>
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:583:+## Phase 4 — Finalize
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:871:3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:875:## Phase 4 — Final clarifications
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:879:## Phase 5 — Present + approve
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:1135:3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:1139:## Phase 4 — Final clarifications
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:1143:## Phase 5 — Present + approve
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:1202:./skills/z-test/SKILL.md:130:4. **Cross-LLM disagreement.** If Gemini and Codex disagree on whether a specific draft is meaningful, surface that disagreement to the user via Phase 5 `AskUserQuestion` — do NOT silently pick one side.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:1208:./skills/z-test/SKILL.md:236:- No `--apply` flag — Phase 5 `AskUserQuestion` is the only write gate. The user can re-run `/z-test` later to add more tests; merge semantics in Phase 7 handle this.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:1244:./agents/gemini-consultant.md:29:- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:1498:./agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:1570:./commands/z-test.md:130:4. **Cross-LLM disagreement.** If Gemini and Codex disagree on whether a specific draft is meaningful, surface that disagreement to the user via Phase 5 `AskUserQuestion` — do NOT silently pick one side.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:1576:./commands/z-test.md:236:- No `--apply` flag — Phase 5 `AskUserQuestion` is the only write gate. The user can re-run `/z-test` later to add more tests; merge semantics in Phase 7 handle this.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:1796:./z-harness/brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:1812:./brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:1827:./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:55:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:1852:./brainstorm-and-research/SPEC.md:266:**`MODE: research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + the question + the doc-fetcher synthesis. Critique for: (1) missing findings — claims that the codebase supports but the draft didn't make; (2) wrong claims — assertions contradicted by the cited source files; (3) undocumented constraints — limits the draft should have noted; (4) hypothesis creep — anywhere the draft snuck in a recommendation despite the "no-recommendation" rule. **Do not recommend an approach yourself.** Return: gaps to fill, errors to correct, no recommendation.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:1960:./z-harness/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:46:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:1986:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2004:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:70:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2008:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:136:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2011:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:198:agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2018:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:224:    40	- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2027:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:329:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2029:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:341:agents/gemini-consultant.md:29:- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2033:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:355:agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2052:./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:59:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2079:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:266:**`MODE: research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + the question + the doc-fetcher synthesis. Critique for: (1) missing findings — claims that the codebase supports but the draft didn't make; (2) wrong claims — assertions contradicted by the cited source files; (3) undocumented constraints — limits the draft should have noted; (4) hypothesis creep — anywhere the draft snuck in a recommendation despite the "no-recommendation" rule. **Do not recommend an approach yourself.** Return: gaps to fill, errors to correct, no recommendation.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2159:./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:46:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2169:./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:74:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2185:./z-harness/brainstorm-and-research/archive/tasks/T002/diff.patch:35:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2368:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1094:./agents/gemini-consultant.md:29:- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2373:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1099:./agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2432:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1163:./brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2472:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1218:./brainstorm-and-research/SPEC.md:266:**`MODE: research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + the question + the doc-fetcher synthesis. Critique for: (1) missing findings — claims that the codebase supports but the draft didn't make; (2) wrong claims — assertions contradicted by the cited source files; (3) undocumented constraints — limits the draft should have noted; (4) hypothesis creep — anywhere the draft snuck in a recommendation despite the "no-recommendation" rule. **Do not recommend an approach yourself.** Return: gaps to fill, errors to correct, no recommendation.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2542:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1311:./z-harness/brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2593:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1370:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/TASKS.md:58:    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2614:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1398:./brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/SPEC.md:266:**`MODE: research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + the question + the doc-fetcher synthesis. Critique for: (1) missing findings — claims that the codebase supports but the draft didn't make; (2) wrong claims — assertions contradicted by the cited source files; (3) undocumented constraints — limits the draft should have noted; (4) hypothesis creep — anywhere the draft snuck in a recommendation despite the "no-recommendation" rule. **Do not recommend an approach yourself.** Return: gaps to fill, errors to correct, no recommendation.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2705:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1498:./z-harness/brainstorm-and-research/archive/tasks/T001/review.prompt.md:55:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2717:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1513:./z-harness/brainstorm-and-research/archive/tasks/T001/diff-v1.patch:46:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2725:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1522:./z-harness/brainstorm-and-research/archive/tasks/T002/review.prompt.md:59:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2779:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1598:./z-harness/brainstorm-and-research/archive/tasks/T001/diff.patch:46:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2790:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1614:./z-harness/brainstorm-and-research/archive/tasks/T002/review.response.md:74:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2834:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1662:./z-harness/brainstorm-and-research/archive/tasks/T002/diff.patch:35:+- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2852:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1683:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:70:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2856:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1688:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:136:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2859:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1691:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:198:agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2866:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1698:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:224:    40	- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2875:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1707:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:329:+- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2877:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1709:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:341:agents/gemini-consultant.md:29:- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:2880:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1715:./z-harness/brainstorm-and-research/archive/tasks/T001/review.response.md:355:agents/codex-consultant.md:40:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:3067:./z-harness/brainstorm-and-research/archive/tasks/T004/review.response.md:1947:    58	    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:3428:- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Gemini: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:3429:- **`research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + original question + scaffolding. Ask Gemini to critique the draft under three headings: **Gaps** (things the draft missed), **Errors** (claims that appear wrong), **Missing constraints** (constraints the reviewer noticed that should be added). **Return RAW — no standard wrapper.** Do NOT ask Gemini to recommend an approach; the consultant prompt must explicitly forbid it. Research is terrain-mapping, not direction-picking.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:3525:- **`debug-hypotheses`** (Phase 4 of `/z-debug`): caller hands you a problem statement + evidence + ranked hypotheses + relevant code. Ask Codex: which hypothesis is most plausible and why? Any missed? For the top one, what's the cheapest experiment to confirm/refute? Be concrete.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:3532:- **`research-review`** (Phase 4 of `/z-research`): caller provides research-note draft + original question + scaffolding. Ask Codex to critique the draft. Does NOT use the standard return wrapper. Return RAW with exactly these sections:
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:3826:   223	   <filled in Phase 4>
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:3838:   235	## Phase 4 — Finalize
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:3997:- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:175) / [skills/z-brainstorm/SKILL.md](/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md:175): the required `chosen_framing` frontmatter field is missing from the BRAINSTORM.md template, and Phase 4 says to “update” a field that was never created. Add `chosen_framing:` to the initial frontmatter with a valid provisional/final value strategy, and ensure restart/abandon branches persist a spec-valid value.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:4005:- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:222) / [skills/z-brainstorm/SKILL.md](/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md:222): Phase 3 writes a `## User choice` placeholder, then Phase 4 says to append another `## User choice` section, producing duplicate sections and making downstream parsing ambiguous. Change Phase 4 to replace the placeholder section in place, or do not emit the section until finalization.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:4013:- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:175) / [skills/z-brainstorm/SKILL.md](/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md:175): the required `chosen_framing` frontmatter field is missing from the BRAINSTORM.md template, and Phase 4 says to “update” a field that was never created. Add `chosen_framing:` to the initial frontmatter with a valid provisional/final value strategy, and ensure restart/abandon branches persist a spec-valid value.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:4021:- **Major** — [commands/z-brainstorm.md](/Users/zeke/dev/z-harness/commands/z-brainstorm.md:222) / [skills/z-brainstorm/SKILL.md](/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md:222): Phase 3 writes a `## User choice` placeholder, then Phase 4 says to append another `## User choice` section, producing duplicate sections and making downstream parsing ambiguous. Change Phase 4 to replace the placeholder section in place, or do not emit the section until finalization.
./z-harness/archive/tasks/T004/review.response.md:46:z-harness/archive/tasks/T005/review.prompt.md:1188:+- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
./z-harness/archive/tasks/T004/review.response.md:48:z-harness/archive/tasks/T005/review.prompt.md:1219:+- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
./z-harness/archive/tasks/T004/review.response.md:64:z-harness/archive/tasks/T005/review.response.md:1203:+- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
./z-harness/archive/tasks/T004/review.response.md:66:z-harness/archive/tasks/T005/review.response.md:1234:+- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
./z-harness/archive/tasks/T004/review.response.md:71:z-harness/archive/tasks/T005/review.response.md:2166:+- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
./z-harness/archive/tasks/T004/review.response.md:73:z-harness/archive/tasks/T005/review.response.md:2197:+- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
./z-harness/archive/tasks/T004/review.response.md:90:z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.human.md:21:- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
./z-harness/archive/tasks/T004/review.response.md:92:z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.human.md:46:- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
./z-harness/archive/tasks/T004/review.response.md:97:z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.human.md:22:- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
./z-harness/archive/tasks/T004/review.response.md:99:z-harness/archive/docs/20260525T081901Z-maintain/proposed/skills.human.md:52:- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
./z-harness/archive/tasks/T004/review.response.md:110:z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.human.diff:28:-- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
./z-harness/archive/tasks/T004/review.response.md:114:z-harness/archive/docs/20260525T081955Z-docs/proposed/diffs/skills.human.diff:77:-- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
./z-harness/archive/tasks/T003/review.prompt.md:1:You are reviewing code that Claude just wrote for task T003: Implement Phase 2 (cross-cutting pass): consultant dispatch + 3-tier classification.
./z-harness/archive/tasks/T003/review.prompt.md:9:      prompt="MODE: cross-cutting-uplift\nrepo_root: <abs>\ncomponents: <COMPONENTS.md verbatim>\nsource_map: <top-50 files by churn over last 90 days, plus each component's entry file (heuristic below)>\nAsk: list cross-component issues (duplicated abstractions, style drift, dead code at module boundaries, public-API drift). For each, emit an explicit `component: <slug-from-MANIFEST>` marker, then classify as global-task | per-component-context | risk.")
./z-harness/archive/tasks/T003/review.prompt.md:26:If `global-task` count > 0 → synthetic component `<slug>-cross-cutting` inserted at top of MANIFEST. Its TASKS.md is hand-written from `global-task` entries (one task per G-NNN), with `**Files:**` lines aggregating affected paths.
./z-harness/archive/tasks/T003/review.prompt.md:29:1. Dispatch shape matches /z-audit Phase 4 (two parallel Agent() calls in one message, subagent_type = bare consultant-primary / consultant-secondary)
./z-harness/archive/tasks/T003/review.prompt.md:31:3. Synthetic plan dir is created at $(dirname $Z_HARNESS_PLAN_DIR)/${Z_HARNESS_SLUG}-cross-cutting only when global-task > 0
./z-harness/archive/tasks/T003/review.prompt.md:32:4. --cross-cutting=skip short-circuits cleanly
./z-harness/archive/tasks/T003/review.prompt.md:36:2. **--cross-cutting=skip short-circuit**: Does the placeholder CROSS-CUTTING.md get written, AND does it skip downstream synthetic-dir logic, AND does it advance correctly to Phase 3?
./z-harness/archive/tasks/T003/review.prompt.md:38:4. **CROSS_DIR path computation**: must use $(dirname $Z_HARNESS_PLAN_DIR)/${Z_HARNESS_SLUG}-cross-cutting form — verify no regex-replace lurking.
./z-harness/archive/tasks/T003/review.prompt.md:39:5. **MANIFEST first-row insert**: synthetic component goes to the FIRST row (not appended), so it processes FIRST in Phase 5.
./z-harness/archive/tasks/T003/review.prompt.md:60:Cross-cutting pass was skipped via --cross-cutting=skip.
./z-harness/archive/tasks/T003/review.prompt.md:62:cp "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase2-cross-cutting.md"
./z-harness/archive/tasks/T003/review.prompt.md:65:  "$(printf '{"phase":2,"name":"cross-cutting","wall_ms":%d,"user_wait_ms":0,"skipped":true}' "$WALL_MS")"
./z-harness/archive/tasks/T003/review.prompt.md:167:CROSS_CUTTING_PROMPT="MODE: cross-cutting-uplift
./z-harness/archive/tasks/T003/review.prompt.md:179:- \`global-task\` — cross-component issues requiring a dedicated plan (duplicated abstractions, global API drift, cross-cutting architectural debt)
./z-harness/archive/tasks/T003/review.prompt.md:235:### Step 6 — Create synthetic cross-cutting plan (if global-task count > 0)
./z-harness/archive/tasks/T003/review.prompt.md:242:CROSS_DIR="$(dirname "$Z_HARNESS_PLAN_DIR")/${Z_HARNESS_SLUG}-cross-cutting"
./z-harness/archive/tasks/T003/review.prompt.md:249:# Spec — <slug>-cross-cutting
./z-harness/archive/tasks/T003/review.prompt.md:251:This synthetic component addresses global-task findings from the cross-cutting pass.
./z-harness/archive/tasks/T003/review.prompt.md:259:# Plan — <slug>-cross-cutting
./z-harness/archive/tasks/T003/review.prompt.md:295:                f"- **Acceptance:** Resolve the cross-cutting issue described in {plan_dir}/CROSS-CUTTING.md#{gnum}.\n"
./z-harness/archive/tasks/T003/review.prompt.md:298:header = "# Tasks — cross-cutting global tasks\n\nGenerated from CROSS-CUTTING.md global-task findings.\n\n"
./z-harness/archive/tasks/T003/review.prompt.md:305:Insert `<slug>-cross-cutting` as the FIRST row in MANIFEST.md:
./z-harness/archive/tasks/T003/review.prompt.md:318:cross_slug = f"{slug}-cross-cutting"
./z-harness/archive/tasks/T003/review.prompt.md:345:cp "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase2-cross-cutting.md"
./z-harness/archive/tasks/T003/review.prompt.md:348:  "$(printf '{"phase":2,"name":"cross-cutting","wall_ms":%d,"user_wait_ms":%d}' \
./z-harness/archive/tasks/per-task-model-selection/review.response.md:300:   144	   - Preserve every `[x]` line untouched unless the user explicitly chose "re-open" in Phase 4.
./z-harness/archive/tasks/per-task-model-selection/review.response.md:442:   144	   - Preserve every `[x]` line untouched unless the user explicitly chose "re-open" in Phase 4.
./z-harness/archive/tasks/T003/review.response.md:20:You are reviewing code that Claude just wrote for task T003: Implement Phase 2 (cross-cutting pass): consultant dispatch + 3-tier classification.
./z-harness/archive/tasks/T003/review.response.md:28:      prompt="MODE: cross-cutting-uplift\nrepo_root: <abs>\ncomponents: <COMPONENTS.md verbatim>\nsource_map: <top-50 files by churn over last 90 days, plus each component's entry file (heuristic below)>\nAsk: list cross-component issues (duplicated abstractions, style drift, dead code at module boundaries, public-API drift). For each, emit an explicit `component: <slug-from-MANIFEST>` marker, then classify as global-task | per-component-context | risk.")
./z-harness/archive/tasks/T003/review.response.md:45:If `global-task` count > 0 → synthetic component `<slug>-cross-cutting` inserted at top of MANIFEST. Its TASKS.md is hand-written from `global-task` entries (one task per G-NNN), with `**Files:**` lines aggregating affected paths.
./z-harness/archive/tasks/T003/review.response.md:48:1. Dispatch shape matches /z-audit Phase 4 (two parallel Agent() calls in one message, subagent_type = bare consultant-primary / consultant-secondary)
./z-harness/archive/tasks/T003/review.response.md:50:3. Synthetic plan dir is created at $(dirname $Z_HARNESS_PLAN_DIR)/${Z_HARNESS_SLUG}-cross-cutting only when global-task > 0
./z-harness/archive/tasks/T003/review.response.md:51:4. --cross-cutting=skip short-circuits cleanly
./z-harness/archive/tasks/T003/review.response.md:55:2. **--cross-cutting=skip short-circuit**: Does the placeholder CROSS-CUTTING.md get written, AND does it skip downstream synthetic-dir logic, AND does it advance correctly to Phase 3?
./z-harness/archive/tasks/T003/review.response.md:57:4. **CROSS_DIR path computation**: must use $(dirname $Z_HARNESS_PLAN_DIR)/${Z_HARNESS_SLUG}-cross-cutting form — verify no regex-replace lurking.
./z-harness/archive/tasks/T003/review.response.md:58:5. **MANIFEST first-row insert**: synthetic component goes to the FIRST row (not appended), so it processes FIRST in Phase 5.
./z-harness/archive/tasks/T003/review.response.md:79:Cross-cutting pass was skipped via --cross-cutting=skip.
./z-harness/archive/tasks/T003/review.response.md:81:cp "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase2-cross-cutting.md"
./z-harness/archive/tasks/T003/review.response.md:84:  "$(printf '{"phase":2,"name":"cross-cutting","wall_ms":%d,"user_wait_ms":0,"skipped":true}' "$WALL_MS")"
./z-harness/archive/tasks/T003/review.response.md:186:CROSS_CUTTING_PROMPT="MODE: cross-cutting-uplift
./z-harness/archive/tasks/T003/review.response.md:198:- \`global-task\` — cross-component issues requiring a dedicated plan (duplicated abstractions, global API drift, cross-cutting architectural debt)
./z-harness/archive/tasks/T003/review.response.md:254:### Step 6 — Create synthetic cross-cutting plan (if global-task count > 0)
./z-harness/archive/tasks/T003/review.response.md:261:CROSS_DIR="$(dirname "$Z_HARNESS_PLAN_DIR")/${Z_HARNESS_SLUG}-cross-cutting"
./z-harness/archive/tasks/T003/review.response.md:268:# Spec — <slug>-cross-cutting
./z-harness/archive/tasks/T003/review.response.md:270:This synthetic component addresses global-task findings from the cross-cutting pass.
./z-harness/archive/tasks/T003/review.response.md:278:# Plan — <slug>-cross-cutting
./z-harness/archive/tasks/T003/review.response.md:314:                f"- **Acceptance:** Resolve the cross-cutting issue described in {plan_dir}/CROSS-CUTTING.md#{gnum}.\n"
./z-harness/archive/tasks/T003/review.response.md:317:header = "# Tasks — cross-cutting global tasks\n\nGenerated from CROSS-CUTTING.md global-task findings.\n\n"
./z-harness/archive/tasks/T003/review.response.md:324:Insert `<slug>-cross-cutting` as the FIRST row in MANIFEST.md:
./z-harness/archive/tasks/T003/review.response.md:337:cross_slug = f"{slug}-cross-cutting"
./z-harness/archive/tasks/T003/review.response.md:364:cp "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase2-cross-cutting.md"
./z-harness/archive/tasks/T003/review.response.md:367:  "$(printf '{"phase":2,"name":"cross-cutting","wall_ms":%d,"user_wait_ms":%d}' \
./z-harness/archive/tasks/T003/review.response.md:920:   709	Cross-cutting pass was skipped via --cross-cutting=skip.
./z-harness/archive/tasks/T003/review.response.md:922:   711	cp "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase2-cross-cutting.md"
./z-harness/archive/tasks/T003/review.response.md:925:   714	  "$(printf '{"phase":2,"name":"cross-cutting","wall_ms":%d,"user_wait_ms":0,"skipped":true}' "$WALL_MS")"
./z-harness/archive/tasks/T003/review.response.md:1027:   816	CROSS_CUTTING_PROMPT="MODE: cross-cutting-uplift
./z-harness/archive/tasks/T003/review.response.md:1039:   828	- \`global-task\` — cross-component issues requiring a dedicated plan (duplicated abstractions, global API drift, cross-cutting architectural debt)
./z-harness/archive/tasks/T003/review.response.md:1095:   884	### Step 6 — Create synthetic cross-cutting plan (if global-task count > 0)
./z-harness/archive/tasks/T003/review.response.md:1102:   891	CROSS_DIR="$(dirname "$Z_HARNESS_PLAN_DIR")/${Z_HARNESS_SLUG}-cross-cutting"
./z-harness/archive/tasks/T003/review.response.md:1109:   898	# Spec — <slug>-cross-cutting
./z-harness/archive/tasks/T003/review.response.md:1111:   900	This synthetic component addresses global-task findings from the cross-cutting pass.
./z-harness/archive/tasks/T003/review.response.md:1119:   908	# Plan — <slug>-cross-cutting
./z-harness/archive/tasks/T003/review.response.md:1155:   944	                f"- **Acceptance:** Resolve the cross-cutting issue described in {plan_dir}/CROSS-CUTTING.md#{gnum}.\n"
./z-harness/archive/tasks/T003/review.response.md:1158:   947	header = "# Tasks — cross-cutting global tasks\n\nGenerated from CROSS-CUTTING.md global-task findings.\n\n"
./z-harness/archive/tasks/T003/review.response.md:1165:   954	Insert `<slug>-cross-cutting` as the FIRST row in MANIFEST.md:
./z-harness/archive/tasks/T003/review.response.md:1178:   967	cross_slug = f"{slug}-cross-cutting"
./z-harness/archive/tasks/T003/review.response.md:1205:   994	cp "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase2-cross-cutting.md"
./z-harness/archive/tasks/T003/review.response.md:1208:   997	  "$(printf '{"phase":2,"name":"cross-cutting","wall_ms":%d,"user_wait_ms":%d}' \
./z-harness/archive/tasks/T003/review.response.md:1234:   101	      prompt="MODE: cross-cutting-uplift\nrepo_root: <abs>\ncomponents: <COMPONENTS.md verbatim>\nsource_map: <top-50 files by churn over last 90 days, plus each component's entry file (heuristic below)>\nAsk: list cross-component issues (duplicated abstractions, style drift, dead code at module boundaries, public-API drift). For each, emit an explicit `component: <slug-from-MANIFEST>` marker, then classify as global-task | per-component-context | risk.")
./z-harness/archive/tasks/T003/review.response.md:1256:   118	If `global-task` count > 0 → synthetic component `<slug>-cross-cutting` inserted at top of MANIFEST. Its TASKS.md is hand-written from `global-task` entries (one task per G-NNN), with `**Files:**` lines aggregating affected paths.
./z-harness/archive/tasks/T003/review.response.md:1263:   125	4. Bundled consult: `consultant-primary` + `consultant-secondary` in parallel on REPORT.md (drops + additions). Same shape as `/z-audit` Phase 4.
./z-harness/archive/tasks/T003/review.response.md:1269:   131	### Sequential implement (`commands/z-uplift.md` Phase 5)
./z-harness/archive/tasks/T003/review.response.md:1284:  1007	For each component in MANIFEST `pending` state (processing synthetic `<slug>-cross-cutting` first if it exists):
./z-harness/archive/tasks/T003/review.response.md:1301:  1024	## Phase 4 — Review gate
./z-harness/archive/tasks/T003/review.response.md:1315:  1038	Use `AskUserQuestion` for this gate. If user aborts, emit `run_end status: aborted_by_user` and exit.
./z-harness/archive/tasks/T003/review.response.md:1317:  1040	Checkpoint: `phase4-review-gate.md`.
./z-harness/archive/tasks/T003/review.response.md:1321:  1044	## Phase 5 — Sequential implement
./z-harness/archive/tasks/T003/review.response.md:1325:  1048	For each component with state `[a] audited` in MANIFEST order (synthetic `<slug>-cross-cutting` first):
./z-harness/archive/tasks/T003/review.response.md:1330:  1053	4. If abort: leave remaining component states unchanged; emit `run_end status: aborted_by_user`; exit.
./z-harness/archive/tasks/T003/review.response.md:1334:  1057	Emit `component_implement_start` / `component_implement_done` telemetry per component.
./z-harness/archive/tasks/T003/review.response.md:1375:- **Major — `commands/z-uplift.md:957-980`**: MANIFEST insertion is not idempotent, so rerunning/resuming Phase 2 with globals will insert duplicate `<slug>-cross-cutting` rows. Check for an existing row with that slug first and update/skip insertion instead of blindly adding a new first row.
./z-harness/archive/tasks/T003/review.response.md:1394:- **Major — `commands/z-uplift.md:957-980`**: MANIFEST insertion is not idempotent, so rerunning/resuming Phase 2 with globals will insert duplicate `<slug>-cross-cutting` rows. Check for an existing row with that slug first and update/skip insertion instead of blindly adding a new first row.
./z-harness/archive/tasks/T003/review-v2.prompt.md:1:You are reviewing code that Claude just wrote for task T003: Implement Phase 2 (cross-cutting pass): consultant dispatch + 3-tier classification.
./z-harness/archive/tasks/T003/review-v2.prompt.md:4:- M1. --cross-cutting=skip control flow not enforced (no else/guard).
./z-harness/archive/tasks/T003/review-v2.prompt.md:19:      prompt="MODE: cross-cutting-uplift\nrepo_root: <abs>\ncomponents: <COMPONENTS.md verbatim>\nsource_map: <top-50 files by churn over last 90 days, plus each component's entry file (heuristic below)>\nAsk: list cross-component issues (duplicated abstractions, style drift, dead code at module boundaries, public-API drift). For each, emit an explicit `component: <slug-from-MANIFEST>` marker, then classify as global-task | per-component-context | risk.")
./z-harness/archive/tasks/T003/review-v2.prompt.md:36:If `global-task` count > 0 → synthetic component `<slug>-cross-cutting` inserted at top of MANIFEST. Its TASKS.md is hand-written from `global-task` entries (one task per G-NNN), with `**Files:**` lines aggregating affected paths.
./z-harness/archive/tasks/T003/review-v2.prompt.md:40:- dispatch shape matches /z-audit Phase 4
./z-harness/archive/tasks/T003/review-v2.prompt.md:43:- --cross-cutting=skip short-circuits
./z-harness/archive/tasks/T003/review-v2.prompt.md:50:   "$(printf '{"phase":2,"name":"cross-cutting","wall_ms":%d,"user_wait_ms":0,"skipped":true}' "$WALL_MS")"
./z-harness/archive/tasks/T003/review-v2.prompt.md:317: ### Step 6 — Create synthetic cross-cutting plan (if global-task count > 0)
./z-harness/archive/tasks/T003/review-v2.prompt.md:325: CROSS_DIR="$(dirname "$Z_HARNESS_PLAN_DIR")/${Z_HARNESS_SLUG}-cross-cutting"
./z-harness/archive/tasks/T003/review-v2.prompt.md:341:-                f"- **Acceptance:** Resolve the cross-cutting issue described in {plan_dir}/CROSS-CUTTING.md#{gnum}.\n"
./z-harness/archive/tasks/T003/review-v2.prompt.md:376:+            f"- **Acceptance:** Resolve the cross-cutting issue described in {plan_dir}/CROSS-CUTTING.md#{gnum}.\n"
./z-harness/archive/tasks/T003/review-v2.prompt.md:379: header = "# Tasks — cross-cutting global tasks\n\nGenerated from CROSS-CUTTING.md global-task findings.\n\n"
./z-harness/archive/tasks/T003/review-v2.prompt.md:383: cross_slug = f"{slug}-cross-cutting"
./z-harness/archive/tasks/T005/review/review.prompt.md:49:+| **Phase 4 — Synthesize + push back** | For each recommendation, articulate one concrete reason it might be wrong. Surface cross-LLM disagreement to user if present. |
./z-harness/archive/tasks/T005/review/review.prompt.md:50:+| **Phase 5 — Approve** | `AskUserQuestion`: approve / modify / abandon. Shortcuts require explicit separate approval. |
./z-harness/archive/tasks/T005/review.prompt.md:1188:+- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
./z-harness/archive/tasks/T005/review.prompt.md:1189:+- `skills/z-maintain-docs/SKILL.md:1` — `z-maintain-docs` — Refreshes stale docs. Phase 2 spawns `doc-updater` subagents with `dedup_tags: true`. Phase 3 surfaces stale memories and TAG_COLLISIONS. Phase 4.5 regenerates MEMORIES-FLAT.md after every write. Supports `--apply` and `--audit` flags.
./z-harness/archive/tasks/T005/review.prompt.md:1191:+- `skills/z-plan-split/SKILL.md:1` — `z-plan-split` — Pre-emptive scope splitter into 2-6 clusters. Enforces kebab-slug security gate. Phase 4 reconciles file-path overlaps from TASKS.md (canonical) against `FILES_TOUCHED` summary. Writes MANIFEST.md and SHARED-CONCERNS.md. MANIFEST uses stable `cluster_id` (C1…CN) for telemetry and `cluster_slug` for on-disk paths.
./z-harness/archive/tasks/T005/review.prompt.md:1193:+- `skills/z-research/SKILL.md:1` — `z-research` — Terrain-mapping pre-plan research. Cost gate at Phase 0 (up to 3 Explores or 1). Phase 4 bundled cross-LLM critique. RESEARCH.md has mandatory `## No-recommendation` section with locked canonical text.
./z-harness/archive/tasks/T005/review.prompt.md:1219:+- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
./z-harness/archive/tasks/T005/review.prompt.md:1228:+  Read `skills/z-amend/SKILL.md` Phase 4 (user gate) and Phase 6 (propagation) for the full checklist.
./z-harness/archive/tasks/T005/review.response.md:1203:+- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
./z-harness/archive/tasks/T005/review.response.md:1204:+- `skills/z-maintain-docs/SKILL.md:1` — `z-maintain-docs` — Refreshes stale docs. Phase 2 spawns `doc-updater` subagents with `dedup_tags: true`. Phase 3 surfaces stale memories and TAG_COLLISIONS. Phase 4.5 regenerates MEMORIES-FLAT.md after every write. Supports `--apply` and `--audit` flags.
./z-harness/archive/tasks/T005/review.response.md:1206:+- `skills/z-plan-split/SKILL.md:1` — `z-plan-split` — Pre-emptive scope splitter into 2-6 clusters. Enforces kebab-slug security gate. Phase 4 reconciles file-path overlaps from TASKS.md (canonical) against `FILES_TOUCHED` summary. Writes MANIFEST.md and SHARED-CONCERNS.md. MANIFEST uses stable `cluster_id` (C1…CN) for telemetry and `cluster_slug` for on-disk paths.
./z-harness/archive/tasks/T005/review.response.md:1208:+- `skills/z-research/SKILL.md:1` — `z-research` — Terrain-mapping pre-plan research. Cost gate at Phase 0 (up to 3 Explores or 1). Phase 4 bundled cross-LLM critique. RESEARCH.md has mandatory `## No-recommendation` section with locked canonical text.
./z-harness/archive/tasks/T005/review.response.md:1234:+- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
./z-harness/archive/tasks/T005/review.response.md:1243:+  Read `skills/z-amend/SKILL.md` Phase 4 (user gate) and Phase 6 (propagation) for the full checklist.
./z-harness/archive/tasks/T005/review.response.md:2166:+- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
./z-harness/archive/tasks/T005/review.response.md:2167:+- `skills/z-maintain-docs/SKILL.md:1` — `z-maintain-docs` — Refreshes stale docs. Phase 2 spawns `doc-updater` subagents with `dedup_tags: true`. Phase 3 surfaces stale memories and TAG_COLLISIONS. Phase 4.5 regenerates MEMORIES-FLAT.md after every write. Supports `--apply` and `--audit` flags.
./z-harness/archive/tasks/T005/review.response.md:2169:+- `skills/z-plan-split/SKILL.md:1` — `z-plan-split` — Pre-emptive scope splitter into 2-6 clusters. Enforces kebab-slug security gate. Phase 4 reconciles file-path overlaps from TASKS.md (canonical) against `FILES_TOUCHED` summary. Writes MANIFEST.md and SHARED-CONCERNS.md. MANIFEST uses stable `cluster_id` (C1…CN) for telemetry and `cluster_slug` for on-disk paths.
./z-harness/archive/tasks/T005/review.response.md:2171:+- `skills/z-research/SKILL.md:1` — `z-research` — Terrain-mapping pre-plan research. Cost gate at Phase 0 (up to 3 Explores or 1). Phase 4 bundled cross-LLM critique. RESEARCH.md has mandatory `## No-recommendation` section with locked canonical text.
./z-harness/archive/tasks/T005/review.response.md:2197:+- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
./z-harness/archive/tasks/T005/review.response.md:2206:+  Read `skills/z-amend/SKILL.md` Phase 4 (user gate) and Phase 6 (propagation) for the full checklist.
./z-harness/archive/tasks/T005/review.response.md:2865:commands/z-audit.md:132:## Phase 4 — Bundled cross-LLM consult on findings
./z-harness/archive/tasks/T005/review.response.md:2871:commands/z-audit.md:159:## Phase 5 — Promote to TASKS.md
./z-harness/archive/tasks/T005/review.response.md:2893:commands/z-review-all.md:95:**Any failure here is a blocker.** Surface the failing log slice to the user before proceeding to Phase 4. Treat the same way as a Prong-A finding of severity `blocker` — `/z-review-all` cannot accept a plan whose own tests are broken.
./z-harness/archive/tasks/T005/review.response.md:2901:commands/z-review-all.md:171:## Phase 5 — Aggregate findings

codex
The repo has a broad dirty worktree, so I’m ignoring unrelated churn and focusing on `commands/z-uplift.md` plus generated mirrors only if needed.
exec
/bin/zsh -lc "nl -ba commands/z-uplift.md | sed -n '1840,2105p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
  1840	
  1841	audited      = []
  1842	bailed       = []
  1843	dep_warnings = []
  1844	total_tasks  = 0
  1845	
  1846	for line in content.splitlines():
  1847	    line = line.strip()
  1848	    if not line.startswith('|') or line.startswith('|---') or line.startswith('| State'):
  1849	        continue
  1850	    cells = [c.strip() for c in line.split('|')]
  1851	    # cells[0] empty, [1]=state, [2]=component, [3]=slug, [4]=findings, [5]=bail, [6]=tasks
  1852	    if len(cells) < 7:
  1853	        continue
  1854	    state    = cells[1]
  1855	    comp     = cells[2]
  1856	    findings = cells[4]
  1857	    tasks_md = cells[6] if len(cells) > 6 else ''
  1858	
  1859	    if '[a] audited' in state:
  1860	        audited.append(comp)
  1861	        # Count tasks in TASKS.md if path is valid
  1862	        if tasks_md and tasks_md not in ('—', '-', ''):
  1863	            tasks_path = tasks_md.strip()
  1864	            try:
  1865	                with open(tasks_path) as tf:
  1866	                    task_text = tf.read()
  1867	                pending = len(re.findall(r'^\s*###\s*\[\s*\]', task_text, re.MULTILINE))
  1868	                total_tasks += pending
  1869	            except OSError:
  1870	                pass
  1871	    elif '[!] bailed' in state:
  1872	        bail_reason = cells[5] if len(cells) > 5 else 'unknown'
  1873	        bailed.append(f"{comp} ({bail_reason.strip()})")
  1874	
  1875	# Count dep-warnings section entries
  1876	dep_section = re.search(r'## Dependents warnings \(post-bail\)(.*?)(?=\n## |\Z)', content, re.DOTALL)
  1877	if dep_section:
  1878	    dep_warnings = [l.strip() for l in dep_section.group(1).splitlines()
  1879	                    if l.strip().startswith('-')]
  1880	
  1881	result = {
  1882	    "audited_count":  len(audited),
  1883	    "total_tasks":    total_tasks,
  1884	    "bailed_list":    bailed,
  1885	    "dep_warn_count": len(dep_warnings),
  1886	    "audited_list":   audited,
  1887	}
  1888	print(json.dumps(result))
  1889	PYEOF
  1890	)"
  1891	
  1892	AUDITED_COUNT="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d['audited_count'])" "$PHASE4_SUMMARY")"
  1893	TOTAL_TASKS="$(python3 -c  "import json,sys; d=json.loads(sys.argv[1]); print(d['total_tasks'])"   "$PHASE4_SUMMARY")"
  1894	BAILED_LIST="$(python3 -c  "import json,sys; d=json.loads(sys.argv[1]); print('\n'.join(d['bailed_list']))" "$PHASE4_SUMMARY")"
  1895	BAILED_COUNT="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(len(d['bailed_list']))" "$PHASE4_SUMMARY")"
  1896	DEP_WARN_COUNT="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d['dep_warn_count'])" "$PHASE4_SUMMARY")"
  1897	```
  1898	
  1899	### Step 2 — Write checkpoint and push-notify
  1900	
  1901	Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/phase4-review-gate.md`:
  1902	
  1903	```bash
  1904	python3 - "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase4-review-gate.md" \
  1905	  "$SLUG" "$PHASE4_SUMMARY" <<'PYEOF'
  1906	import json, sys, os
  1907	from datetime import datetime, timezone
  1908	
  1909	out_path = sys.argv[1]
  1910	slug     = sys.argv[2]
  1911	d        = json.loads(sys.argv[3])
  1912	
  1913	lines = [
  1914	    f"# Phase 4 — Review gate checkpoint — {slug}",
  1915	    f"",
  1916	    f"Generated: {datetime.now(timezone.utc).isoformat()}",
  1917	    f"",
  1918	    f"## Queue summary",
  1919	    f"- Components audited: {d['audited_count']}",
  1920	    f"- Total tasks queued: {d['total_tasks']}",
  1921	    f"- Bailed components:  {len(d['bailed_list'])}",
  1922	    f"- Dep warnings:       {d['dep_warn_count']}",
  1923	    f"",
  1924	]
  1925	if d['bailed_list']:
  1926	    lines.append("## Bailed components")
  1927	    for b in d['bailed_list']:
  1928	        lines.append(f"- {b}")
  1929	    lines.append("")
  1930	
  1931	os.makedirs(os.path.dirname(out_path), exist_ok=True)
  1932	with open(out_path, "w") as f:
  1933	    f.write("\n".join(lines) + "\n")
  1934	print("wrote phase4-review-gate.md")
  1935	PYEOF
  1936	```
  1937	
  1938	Push-notify the user with the queue summary.
  1939	
  1940	Present the following summary (no AskUser — this is informational only):
  1941	
  1942	> **Uplift queue ready — `<slug>`**
  1943	>
  1944	> - Components audited: `<AUDITED_COUNT>`
  1945	> - Total tasks queued: `<TOTAL_TASKS>` (across all audited components)
  1946	> - Bailed components: `<BAILED_COUNT>` `<if > 0: list each on its own line>`
  1947	> - Dependents warnings: `<DEP_WARN_COUNT>` `<if > 0: note "see MANIFEST.md Dependents warnings section">`
  1948	>
  1949	> Phase 5 will prompt you per-component before dispatching any implementation.
  1950	
  1951	### Step 3 — Phase telemetry
  1952	
  1953	```bash
  1954	cp "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase4-review-gate.md"
  1955	WALL_MS=$(( $(date +%s%3N) - T0 ))
  1956	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  1957	  "$(printf '{"phase":4,"name":"review-gate","wall_ms":%d,"user_wait_ms":0,"audited":%d,"total_tasks":%d,"bailed":%d}' \
  1958	     "$WALL_MS" "$AUDITED_COUNT" "$TOTAL_TASKS" "$BAILED_COUNT")"
  1959	```
  1960	
  1961	---
  1962	
  1963	## Phase 5 — Sequential implement
  1964	
  1965	Record `T0=$(date +%s%3N)` at phase start.
  1966	
  1967	### Step 1 — Build the ordered implementation queue
  1968	
  1969	Parse MANIFEST.md to collect rows with state `[a] audited` **plus** any `[i] implementing` rows (interrupted on a prior invocation). Apply the ordering rule: the synthetic `<slug>-cross-cutting` row is always processed first, regardless of its physical position in the table.
  1970	
  1971	```bash
  1972	IMPL_QUEUE="$(python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$SLUG" <<'PYEOF'
  1973	import re, sys, json
  1974	
  1975	manifest_path = sys.argv[1]
  1976	slug          = sys.argv[2]
  1977	
  1978	with open(manifest_path) as f:
  1979	    content = f.read()
  1980	
  1981	cross_cutting_row = None
  1982	other_rows        = []
  1983	
  1984	for line in content.splitlines():
  1985	    line = line.strip()
  1986	    if not line.startswith('|') or line.startswith('|---') or line.startswith('| State'):
  1987	        continue
  1988	    cells = [c.strip() for c in line.split('|')]
  1989	    # cells[0]=empty, [1]=state, [2]=component, [3]=slug, [4]=findings, [5]=bail, [6]=tasks
  1990	    if len(cells) < 7:
  1991	        continue
  1992	    state    = cells[1]
  1993	    comp     = cells[2]
  1994	    row_slug = cells[3]
  1995	    tasks_md = cells[6] if len(cells) > 6 else ''
  1996	
  1997	    actionable = '[a] audited' in state or '[i] implementing' in state
  1998	    if not actionable:
  1999	        continue
  2000	
  2001	    row = {
  2002	        "state":     state,
  2003	        "component": comp,
  2004	        "slug":      row_slug,
  2005	        "tasks_md":  tasks_md,
  2006	        "implementing": '[i] implementing' in state,
  2007	    }
  2008	
  2009	    # Synthetic cross-cutting goes first
  2010	    if row_slug.endswith('-cross-cutting') or comp == '(global)':
  2011	        cross_cutting_row = row
  2012	    else:
  2013	        other_rows.append(row)
  2014	
  2015	ordered = ([cross_cutting_row] if cross_cutting_row else []) + other_rows
  2016	print(json.dumps(ordered))
  2017	PYEOF
  2018	)"
  2019	```
  2020	
  2021	### Step 2 — Per-component implement loop
  2022	
  2023	Iterate over each row in `IMPL_QUEUE`. For each component, execute Steps 2a through 2e.
  2024	
  2025	#### Step 2a — Handle `[i] implementing` (interrupted resume)
  2026	
  2027	If the row state is `[i] implementing` (set on a prior invocation that was interrupted before completion):
  2028	
  2029	Log a `user_wait_start` event, then present `AskUserQuestion`:
  2030	
  2031	> Component `<component>` is in state `[i] implementing` — it was being implemented when the last invocation was interrupted.
  2032	>
  2033	> How would you like to proceed?
  2034	> 1. Resume — run `/z-implement-all --tasks=<tasks_md>` now to continue implementation
  2035	> 2. Mark as done — the implementation was completed manually; update MANIFEST to `[x] done`
  2036	> 3. Skip — mark as `[s] skipped: user` and move on
  2037	> 4. Abort — leave all remaining components unchanged and exit
  2038	
  2039	Log `user_wait_end` after the user responds.
  2040	
  2041	Handle the response:
  2042	
  2043	- **Option 1 (Resume):** continue into Step 2b (treat as a normal proceed).
  2044	- **Option 2 (Mark done):** run the manifest_write block from Step 2d with state `[x] done`, emit `component_implement_done` with `outcome: "marked_done_manually"`, continue to the next component.
  2045	- **Option 3 (Skip):** run the manifest_write block from Step 2d with state `[s] skipped: user`, continue to the next component.
  2046	- **Option 4 (Abort):** go to Step 2e (abort path).
  2047	
  2048	#### Step 2b — AskUser gate (normal `[a] audited` components)
  2049	
  2050	If the row state was `[a] audited` (not a resume from `[i] implementing`):
  2051	
  2052	Count pending tasks in the TASKS.md to show the user:
  2053	
  2054	```bash
  2055	COMP_PENDING_TASKS="$(python3 - "$COMP_TASKS_MD" <<'PYEOF'
  2056	import re, sys
  2057	try:
  2058	    with open(sys.argv[1]) as f:
  2059	        text = f.read()
  2060	    print(len(re.findall(r'^\s*###\s*\[\s*\]', text, re.MULTILINE)))
  2061	except OSError:
  2062	    print(0)
  2063	PYEOF
  2064	)"
  2065	```
  2066	
  2067	Log `user_wait_start`, then present `AskUserQuestion`:
  2068	
  2069	> Implement `<component>` (`<COMP_PENDING_TASKS>` pending tasks)?
  2070	>
  2071	> Tasks file: `<COMP_TASKS_MD>`
  2072	>
  2073	> Options:
  2074	> 1. Proceed — dispatch `/z-implement-all --tasks=<COMP_TASKS_MD>`
  2075	> 2. Skip this component — mark as skipped and move on
  2076	> 3. Abort uplift — leave remaining components unchanged and exit
  2077	
  2078	Log `user_wait_end` after the user responds.
  2079	
  2080	Handle the response:
  2081	
  2082	- **Proceed:** continue into Step 2c.
  2083	- **Skip:** run the manifest_write block in Step 2d with state `[s] skipped: user`; continue to next component.
  2084	- **Abort:** go to Step 2e (abort path).
  2085	
  2086	#### Step 2c — Dispatch implementation
  2087	
  2088	Emit `component_implement_start` event and mark MANIFEST `[i] implementing` BEFORE dispatch (so an interrupt is detectable on next resume):
  2089	
  2090	```bash
  2091	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" component_implement_start \
  2092	  "$(printf '{"component":"%s","tasks_md":"%s"}' "$COMP_SLUG" "$COMP_TASKS_MD")"
  2093	
  2094	python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "[i] implementing" <<'PYEOF'
  2095	import re, sys, os
  2096	
  2097	def manifest_write(path, content):
  2098	    tmp = path + ".tmp"
  2099	    with open(tmp, "w") as f:
  2100	        f.write(content)
  2101	    os.replace(tmp, path)
  2102	
  2103	manifest_path = sys.argv[1]
  2104	comp_slug     = sys.argv[2]
  2105	new_state     = sys.argv[3]

exec
/bin/zsh -lc "git diff -- commands/z-uplift.md | sed -n '1,260p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
exec
/bin/zsh -lc "nl -ba commands/z-uplift.md | sed -n '2105,2225p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
  2105	new_state     = sys.argv[3]
  2106	
  2107	with open(manifest_path) as f:
  2108	    content = f.read()
  2109	
  2110	def replace_row(m):
  2111	    row   = m.group(0)
  2112	    cells = row.split('|')
  2113	    if len(cells) < 8:
  2114	        return row
  2115	    if cells[3].strip() != comp_slug:
  2116	        return row
  2117	    cells[1] = f" {new_state} "
  2118	    return '|'.join(cells)
  2119	
  2120	pattern = re.compile(
  2121	    r'\|[^|\n]*\|\s*[^|\n]*\|\s*' + re.escape(comp_slug) + r'\s*\|[^\n]*\|',
  2122	    re.MULTILINE
  2123	)
  2124	updated = pattern.sub(replace_row, content)
  2125	manifest_write(manifest_path, updated)
  2126	print(f"marked {comp_slug} as {new_state}")
  2127	PYEOF
  2128	```
  2129	
  2130	Present the `/z-implement-all` invocation command to the user and instruct them to run it:
  2131	
  2132	> Run the following command to implement `<component>`:
  2133	>
  2134	> `/z-implement-all --tasks=<COMP_TASKS_MD>`
  2135	>
  2136	> When `/z-implement-all` completes, re-invoke `/z-uplift` to continue with the next component.
  2137	
  2138	Then **exit** the current `/z-uplift` invocation cleanly (do not attempt to wait for `/z-implement-all` inline — it is a separate slash command that the user runs). The next `/z-uplift` invocation will detect the `[i] implementing` row and check completion via Step 2a above.
  2139	
  2140	Note: "completion detection" on resume (Step 2a option 2) works as follows — the user can manually mark `[x] done` after `/z-implement-all` finishes, or they can re-invoke with option 1 (Resume) which re-presents the `/z-implement-all` command for any remaining pending tasks.
  2141	
  2142	#### Step 2d — MANIFEST state update helper
  2143	
  2144	This Python block is the canonical `manifest_write` helper for Phase 5 state transitions. Invoke it with the target `new_state` string:
  2145	
  2146	```bash
  2147	python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "<new_state>" <<'PYEOF'
  2148	import re, sys, os
  2149	
  2150	def manifest_write(path, content):
  2151	    tmp = path + ".tmp"
  2152	    with open(tmp, "w") as f:
  2153	        f.write(content)
  2154	    os.replace(tmp, path)
  2155	
  2156	manifest_path = sys.argv[1]
  2157	comp_slug     = sys.argv[2]
  2158	new_state     = sys.argv[3]
  2159	
  2160	with open(manifest_path) as f:
  2161	    content = f.read()
  2162	
  2163	def replace_row(m):
  2164	    row   = m.group(0)
  2165	    cells = row.split('|')
  2166	    if len(cells) < 8:
  2167	        return row
  2168	    if cells[3].strip() != comp_slug:
  2169	        return row
  2170	    cells[1] = f" {new_state} "
  2171	    return '|'.join(cells)
  2172	
  2173	pattern = re.compile(
  2174	    r'\|[^|\n]*\|\s*[^|\n]*\|\s*' + re.escape(comp_slug) + r'\s*\|[^\n]*\|',
  2175	    re.MULTILINE
  2176	)
  2177	updated = pattern.sub(replace_row, content)
  2178	manifest_write(manifest_path, updated)
  2179	print(f"marked {comp_slug} as {new_state}")
  2180	PYEOF
  2181	```
  2182	
  2183	Valid `new_state` values used in Phase 5: `[i] implementing`, `[x] done`, `[s] skipped: user`.
  2184	
  2185	#### Step 2e — Abort path
  2186	
  2187	When the user chooses "Abort" in any AskUser gate above:
  2188	
  2189	1. Do NOT modify the current component's MANIFEST row (leave it in `[a] audited` or `[i] implementing`).
  2190	2. Do NOT modify any subsequent component's MANIFEST row.
  2191	3. Log `run_end` with `status: aborted_by_user`:
  2192	
  2193	```bash
  2194	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_end \
  2195	  "$(printf '{"slug":"%s","status":"aborted_by_user","aborted_at_component":"%s"}' \
  2196	     "$SLUG" "$COMP_SLUG")"
  2197	```
  2198	
  2199	4. Exit cleanly. Output the message:
  2200	
  2201	> Uplift aborted. Re-invoke `/z-uplift` to resume from `<component>`.
  2202	
  2203	### Step 3 — Emit `component_implement_done` on successful manual-done marking
  2204	
  2205	When the user selects "Mark as done" (Step 2a option 2), emit:
  2206	
  2207	```bash
  2208	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" component_implement_done \
  2209	  "$(printf '{"component":"%s","outcome":"marked_done_manually"}' "$COMP_SLUG")"
  2210	```
  2211	
  2212	### Step 4 — Phase checkpoint and telemetry
  2213	
  2214	After all components in the queue have been handled (or after the user exits cleanly):
  2215	
  2216	```bash
  2217	cp "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase5-implement.md"
  2218	WALL_MS=$(( $(date +%s%3N) - T0 ))
  2219	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  2220	  "$(printf '{"phase":5,"name":"sequential-implement","wall_ms":%d,"user_wait_ms":%d}' \
  2221	     "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
  2222	```
  2223	
  2224	---
  2225	

exec
/bin/zsh -lc "git diff -- commands/z-uplift.md | sed -n '260,620p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
codex
I found one direct contract break around dispatch/wait semantics and am checking whether the MANIFEST update and task counting code have hidden correctness issues, since those affect the acceptance criteria more than stylistic concerns.
exec
/bin/zsh -lc 'rg -n "''^###'"\\s*\\[|"'^- '"\\[|"'^## TASK|''^### TASK|'"\\*\\*Status:\\*\\*\" z-harness/plans commands skills -g 'TASKS.md' -g '*.md' | head -n 120" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "rg -n \"\\[i\\] implementing|\\[a\\] audited|\\[x\\] done|\\[s\\] skipped|MANIFEST\" commands/z-uplift.md z-harness/plans/tiered-quality-uplift -S" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
z-harness/plans/portable-harness/TASKS.md:15:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:28:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:40:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:51:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:66:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:80:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:91:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:104:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:113:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:125:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:136:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:147:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:158:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:170:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:180:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:196:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:206:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:216:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:225:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:235:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:245:- **Status:** `[ ]`
z-harness/plans/portable-harness/TASKS.md:254:- **Status:** `[ ]`
skills/z-review-all/SKILL.md:247:- [from gemini | from codex | both] <finding>
skills/z-review-all/SKILL.md:299:### [ ] T-REV-001 — [blocker] <short title>
skills/z-review-all/SKILL.md:309:### [ ] T-REV-002 — [major] Amend spec: <short title>
skills/z-review-all/SKILL.md:320:### [ ] T-REV-003 — [major] Supersedes T0NN: <short title>
commands/z-review-all.md:272:- [from gemini | from codex | both] <finding>
commands/z-review-all.md:324:### [ ] T-REV-001 — [blocker] <short title>
commands/z-review-all.md:334:### [ ] T-REV-002 — [major] Amend spec: <short title>
commands/z-review-all.md:345:### [ ] T-REV-003 — [major] Supersedes T0NN: <short title>
skills/z-test/SKILL.md:162:**Status:** drafted (awaiting /z-implement-all)
commands/z-improve.md:83:**Status:** draft — under discussion
commands/z-improve.md:164:1. Update the improvements doc's `**Status:**` to `complete`.
commands/z-plan-light.md:144:**Status:** approved (not yet shipped)
commands/z-plan-light.md:161:- [ ] <criterion 1>
commands/z-plan-light.md:162:- [ ] <criterion 2>
skills/z-debug/SKILL.md:451:- [ ] <regression test path + what it should cover>
skills/z-debug/SKILL.md:452:- [ ] <SPEC.md / docs/llm/<concept>.json update with the invariant that was violated>
skills/z-debug/SKILL.md:453:- [ ] <monitoring/alerting addition>
skills/z-debug/SKILL.md:454:- [ ] <other follow-ups>
commands/z-test.md:162:**Status:** drafted (awaiting /z-implement-all)
commands/z-fix.md:147:**Status:** approved (not yet shipped)
commands/z-fix.md:170:- [ ] <criterion 1>
commands/z-fix.md:171:- [ ] <criterion 2>
commands/z-fix.md:272:- [ ] <follow-up 1>
commands/z-fix.md:273:- [ ] <follow-up 2>
commands/z-amend.md:78:### TASKS.md  (full mode only)
skills/z-plan-light/SKILL.md:145:**Status:** approved (not yet shipped)
skills/z-plan-light/SKILL.md:162:- [ ] <criterion 1>
skills/z-plan-light/SKILL.md:163:- [ ] <criterion 2>
commands/z-uplift.md:1717:### [ ] T001 — [SEVERITY] short subject
commands/z-uplift.md:1724:### [ ] T002 — [SEVERITY] ...
z-harness/plans/portable-harness/archive/20260524T094344Z-portable-harness/TASKS.md:15:- **Status:** `[ ]`
z-harness/plans/portable-harness/archive/20260524T094344Z-portable-harness/TASKS.md:28:- **Status:** `[ ]`
z-harness/plans/portable-harness/archive/20260524T094344Z-portable-harness/TASKS.md:40:- **Status:** `[ ]`
z-harness/plans/portable-harness/archive/20260524T094344Z-portable-harness/TASKS.md:51:- **Status:** `[ ]`
z-harness/plans/portable-harness/archive/20260524T094344Z-portable-harness/TASKS.md:66:- **Status:** `[ ]`
z-harness/plans/portable-harness/archive/20260524T094344Z-portable-harness/TASKS.md:80:- **Status:** `[ ]`
z-harness/plans/portable-harness/archive/20260524T094344Z-portable-harness/TASKS.md:91:- **Status:** `[ ]`
z-harness/plans/portable-harness/archive/20260524T094344Z-portable-harness/TASKS.md:104:- **Status:** `[ ]`
z-harness/plans/portable-harness/archive/20260524T094344Z-portable-harness/TASKS.md:113:- **Status:** `[ ]`
z-harness/plans/portable-harness/archive/20260524T094344Z-portable-harness/TASKS.md:125:- **Status:** `[ ]`
z-harness/plans/portable-harness/archive/20260524T094344Z-portable-harness/TASKS.md:136:- **Status:** `[ ]`
z-harness/plans/portable-harness/archive/20260524T094344Z-portable-harness/TASKS.md:147:- **Status:** `[ ]`
z-harness/plans/portable-harness/archive/20260524T094344Z-portable-harness/TASKS.md:158:- **Status:** `[ ]`
z-harness/plans/portable-harness/archive/20260524T094344Z-portable-harness/TASKS.md:170:- **Status:** `[ ]`
z-harness/plans/portable-harness/archive/20260524T094344Z-portable-harness/TASKS.md:180:- **Status:** `[ ]`
commands/z-audit.md:170:### [ ] T001 — [SEVERITY] short subject
commands/z-audit.md:178:### [ ] T002 — [SEVERITY] ...
skills/z-amend/SKILL.md:81:### TASKS.md  (full mode only)
commands/z-debug.md:458:- [ ] <regression test path + what it should cover>
commands/z-debug.md:459:- [ ] <SPEC.md / docs/llm/<concept>.json update with the invariant that was violated>
commands/z-debug.md:460:- [ ] <monitoring/alerting addition>
commands/z-debug.md:461:- [ ] <other follow-ups>
commands/z-mr-review.md:668:- [ ] T-MR-NNN. <title>
z-harness/plans/z-audit-plan/SPEC.md:15:### [NEW] `commands/z-audit-plan.md`
z-harness/plans/z-audit-plan/SPEC.md:93:### [NEW] `skills/z-audit-plan/SKILL.md`
z-harness/plans/z-audit-plan/SPEC.md:110:### [MODIFY] `commands/z-plan.md`
z-harness/plans/z-audit-plan/SPEC.md:129:### [MODIFY] `exports/agy/agy-plugin.yaml`
skills/z-improve/SKILL.md:84:**Status:** draft — under discussion
skills/z-improve/SKILL.md:215:1. Update the improvements doc's `**Status:**` to `complete`.
z-harness/plans/tiered-quality-uplift/TASKS.md:7:### [x] T001 — Create commands/z-uplift.md skeleton with Setup + STYLE.md gate + CLI flags
z-harness/plans/tiered-quality-uplift/TASKS.md:17:### [x] T002 — Implement Phase 1 (decomposition): polyglot detection + COMPONENTS.md + AskUser gate
z-harness/plans/tiered-quality-uplift/TASKS.md:31:### [x] T003 — Implement Phase 2 (cross-cutting pass): consultant dispatch + 3-tier classification
z-harness/plans/tiered-quality-uplift/TASKS.md:45:### [x] T004 — Implement Phase 3 (per-component audit loop) with STYLE injection + cross-cutting context + bail
z-harness/plans/tiered-quality-uplift/TASKS.md:64:### [~] T005 — Implement Phase 4 (review gate) + Phase 5 (sequential implement loop)
z-harness/plans/tiered-quality-uplift/TASKS.md:77:### [ ] T006 — MANIFEST.md schema + resume logic + --retry-bailed / --refresh-component flags
z-harness/plans/tiered-quality-uplift/TASKS.md:92:### [ ] T007 — Telemetry events: full component lifecycle wiring
z-harness/plans/tiered-quality-uplift/TASKS.md:101:### [ ] T008 — Skill wrapper + docs concept entry + README listing
z-harness/plans/tiered-quality-uplift/TASKS.md:114:### [ ] T009 — Multi-IDE export: cursor + codex + agy
z-harness/plans/tiered-quality-uplift/TASKS.md:130:### [ ] T010 — Smoke test against this repo
z-harness/plans/z-audit-plan/TASKS.md:5:### [ ] T001 — Create core command commands/z-audit-plan.md
z-harness/plans/z-audit-plan/TASKS.md:11:### [ ] T002 — Create workspace skill skills/z-audit-plan/SKILL.md
z-harness/plans/z-audit-plan/TASKS.md:17:### [ ] T003 — Update commands/z-plan.md recommendations
z-harness/plans/z-audit-plan/TASKS.md:23:### [ ] T004 — Register in agy-plugin.yaml configuration
z-harness/plans/z-audit-plan/TASKS.md:29:### [ ] T005 — Run export scripts and verify
z-harness/plans/plan-decompose/TASKS.md:5:- [x] **T001 — Create `cluster-planner` agent**
z-harness/plans/plan-decompose/TASKS.md:23:- [x] **T002 — Create `/z-plan-split` command + skill mirror**
z-harness/plans/plan-decompose/TASKS.md:43:- [x] **T003 — Extend `/z-implement-all` for nested-slug discovery**
z-harness/plans/plan-decompose/TASKS.md:65:- [x] **T004 — Update README with `/z-plan-split` documentation**
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:7:### [ ] T001 — Create commands/z-uplift.md skeleton with Setup + STYLE.md gate + CLI flags
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:17:### [ ] T002 — Implement Phase 1 (decomposition): polyglot detection + COMPONENTS.md + AskUser gate
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:30:### [ ] T003 — Implement Phase 2 (cross-cutting pass): consultant dispatch + 3-tier classification
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:43:### [ ] T004 — Implement Phase 3 (per-component audit loop) with STYLE injection + cross-cutting context + bail
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:61:### [ ] T005 — Implement Phase 4 (review gate) + Phase 5 (sequential implement loop)
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:74:### [ ] T006 — MANIFEST.md schema + resume logic + --retry-bailed / --refresh-component flags
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:85:### [ ] T007 — Telemetry events: full component lifecycle wiring
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:94:### [ ] T008 — Skill wrapper + docs concept entry + README listing
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:107:### [ ] T009 — Multi-IDE export: cursor + codex + agy
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:123:### [ ] T010 — Smoke test against this repo
z-harness/plans/plan-bail-router/TASKS.md:5:**Status:** [x]
z-harness/plans/plan-bail-router/TASKS.md:14:- [ ] `agents/planning-router.md` exists with Haiku/read-only frontmatter.
z-harness/plans/plan-bail-router/TASKS.md:15:- [ ] Agent return shape matches SPEC exactly.
z-harness/plans/plan-bail-router/TASKS.md:16:- [ ] Agent docs/memory include `planning-router`.
z-harness/plans/plan-bail-router/TASKS.md:17:- [ ] Malformed input and route-loop behavior are specified.
z-harness/plans/plan-bail-router/TASKS.md:23:**Status:** [x]
z-harness/plans/plan-bail-router/TASKS.md:32:- [ ] Sentineled `Plan Route Check` blocks exist in all four files.
z-harness/plans/plan-bail-router/TASKS.md:33:- [ ] Existing escalation text is replaced or aliased so no duplicate/conflicting user-facing prompts remain.
z-harness/plans/plan-bail-router/TASKS.md:34:- [ ] `$CURRENT_ARCHIVE_DIR`, `route-decision.md`, and `plan_route_decision` are specified.
z-harness/plans/plan-bail-router/TASKS.md:35:- [ ] `/z-do` can route to `/z-plan-light`, `/z-plan`, `/z-research`, `/z-brainstorm`, `/z-fix`, or `/z-debug` only under SPEC conditions.

 succeeded in 0ms:
z-harness/plans/tiered-quality-uplift/SPEC.md:34:- **Phase 2 — Cross-cutting pass** — dispatch `consultant-primary` + `consultant-secondary` in parallel on a curated source map AND STYLE.md (if present); merge findings into `CROSS-CUTTING.md` with three-tier classification (`global-task` / `per-component-context` / `risk`). Style-drift findings are explicitly called out (cite STYLE.md rule IDs). `global-task` items become a synthetic component named `<slug>-cross-cutting` inserted FIRST in MANIFEST.
z-harness/plans/tiered-quality-uplift/SPEC.md:35:- **Phase 3 — Per-component audits** — for each component in MANIFEST order: dispatch `auditor` agents per dimension in parallel (mirroring `/z-audit` Phases 2–6 inline); inject STYLE.md as the authoritative rubric for `cleanliness` and `design` dimensions (if STYLE.md present); read CROSS-CUTTING.md `per-component-context` entries as additional input; produce per-component `REPORT.md` + `TASKS.md` in sibling plan dir `z-harness/plans/<slug>-<component>/`; inherit `/z-audit`'s >30-findings / >10-CRIT-HIGH auto-bail; on bail, run cheap text-grep across other components for the bailed component's symbols/paths and warn user. Update MANIFEST per-component state after each.
z-harness/plans/tiered-quality-uplift/SPEC.md:37:- **Phase 5 — Sequential implement** — for each non-bailed component in MANIFEST order: AskUser gate (proceed / skip / abort); invoke `/z-implement-all --tasks=z-harness/plans/<slug>-<component>/TASKS.md`; update MANIFEST state to `[x] done` on success.
z-harness/plans/tiered-quality-uplift/SPEC.md:54:├── MANIFEST.md                                      ← component table + state (resume authority)
z-harness/plans/tiered-quality-uplift/SPEC.md:101:      prompt="MODE: cross-cutting-uplift\nrepo_root: <abs>\ncomponents: <COMPONENTS.md verbatim>\nsource_map: <top-50 files by churn over last 90 days, plus each component's entry file (heuristic below)>\nAsk: list cross-component issues (duplicated abstractions, style drift, dead code at module boundaries, public-API drift). For each, emit an explicit `component: <slug-from-MANIFEST>` marker, then classify as global-task | per-component-context | risk.")
z-harness/plans/tiered-quality-uplift/SPEC.md:118:If `global-task` count > 0 → synthetic component `<slug>-cross-cutting` inserted at top of MANIFEST. Its TASKS.md is hand-written from `global-task` entries (one task per G-NNN), with `**Files:**` lines aggregating affected paths.
z-harness/plans/tiered-quality-uplift/SPEC.md:121:For each component in MANIFEST `pending` state:
z-harness/plans/tiered-quality-uplift/SPEC.md:122:1. Mark MANIFEST state `[~] auditing` IMMEDIATELY before dispatch (so an interrupt mid-audit is detectable by resume logic).
z-harness/plans/tiered-quality-uplift/SPEC.md:123:2. Dispatch one `auditor` subagent per `--dimensions` value in parallel. Prompt fields: `target_path`, `dimension`, `cross_cutting_context` (the verbatim `per-component-context` entries from CROSS-CUTTING.md whose `component:` marker matches this component's MANIFEST slug — exact slug match, NOT free-text), and `rubric_path` (set to absolute path of `./STYLE.md` when dimension ∈ {`cleanliness`, `design`} AND STYLE.md is present AND `--no-style` was NOT passed; empty string otherwise so the auditor falls back to its generic-dimension rubric). The auditor reads STYLE.md itself — never inline the file's content into the prompt.
z-harness/plans/tiered-quality-uplift/SPEC.md:126:5. Auto-bail check: count CRITICAL+HIGH and total findings. If >10 CRIT-HIGH OR >30 total → mark MANIFEST `[!] bailed: crit_high_volume` (or `bailed: spec_problem` for STATUS: spec_problem from auditor); write partial REPORT.md; run cheap text-grep `git grep -l "<component-basename>"` across other components, append a "Potential dependents (text-grep — incomplete; validate manually for critical APIs)" section to REPORT.md and to MANIFEST.md's `Dependents warnings` section; skip TASKS.md generation; continue to next component.
z-harness/plans/tiered-quality-uplift/SPEC.md:129:8. Mark MANIFEST state `[a] audited`.
z-harness/plans/tiered-quality-uplift/SPEC.md:132:For each component with state `[a] audited`:
z-harness/plans/tiered-quality-uplift/SPEC.md:135:3. On completion: mark MANIFEST `[x] done`.
z-harness/plans/tiered-quality-uplift/SPEC.md:136:4. On user-skip: mark MANIFEST `[s] skipped: user`.
z-harness/plans/tiered-quality-uplift/SPEC.md:137:5. On abort: mark MANIFEST state for this and remaining components left unchanged; log `run_end status: aborted_by_user`; exit.
z-harness/plans/tiered-quality-uplift/SPEC.md:141:### `commands/z-uplift.md` — MANIFEST.md shape
z-harness/plans/tiered-quality-uplift/SPEC.md:143:# Uplift MANIFEST — <slug>
z-harness/plans/tiered-quality-uplift/SPEC.md:151:| [x] done | <slug>-cross-cutting | (global) | 4 (2 HIGH) | — | z-harness/plans/<slug>-cross-cutting/TASKS.md |
z-harness/plans/tiered-quality-uplift/SPEC.md:152:| [a] audited | crates/foo | foo | 8 (1 HIGH) | — | z-harness/plans/<slug>-foo/TASKS.md |
z-harness/plans/tiered-quality-uplift/SPEC.md:160:States: `[ ] pending` `[~] auditing` `[a] audited` `[i] implementing` `[x] done` `[!] bailed: <reason>` `[s] skipped: <reason>`.
z-harness/plans/tiered-quality-uplift/SPEC.md:162:Resume: on re-invoke, orchestrator parses MANIFEST, identifies next non-terminal state, resumes at the matching phase (audit or implement). `--retry-bailed` and `--refresh-component <name>` mutate states accordingly.
z-harness/plans/tiered-quality-uplift/SPEC.md:204:- MANIFEST.md is the resume authority; no parallel state file.
z-harness/plans/tiered-quality-uplift/SPEC.md:205:- Components processed sequentially in MANIFEST order; synthetic `-cross-cutting` first if it exists.
z-harness/plans/tiered-quality-uplift/SPEC.md:211:- Text-grep dependency reporting on bail misses reflection / string-based imports — output is labeled "Potential dependents (text-grep — incomplete)" in REPORT.md and MANIFEST.md to avoid false confidence.
z-harness/plans/tiered-quality-uplift/SPEC.md:225:- Idempotent: re-invoking `/z-uplift` with no flags resumes at the next non-terminal MANIFEST state.
z-harness/plans/tiered-quality-uplift/SPEC.md:238:- All components bail → MANIFEST shows nothing in `[a] audited` state; Phase 5 has nothing to do; recommend user run `/z-plan` on the bailed components individually.
z-harness/plans/tiered-quality-uplift/SPEC.md:239:- User re-invokes mid-implement (Ctrl-C during Phase 5) → MANIFEST shows last component `[i] implementing`. Re-invoke detects this, asks user: resume with `/z-implement-all` on this component / mark `[s] skipped` / mark `[x] done` (if they finished manually) / abort.
commands/z-uplift.md:73:Check for an existing slug dir in the canonical plans directory (`z-harness/plans/`). If a MANIFEST.md is found there, this is a **resume** — skip decomposition phases and jump to the next non-terminal MANIFEST state. If only a slug collision without MANIFEST, prompt the user to confirm or choose a different slug.
commands/z-uplift.md:221:- Is there a `MANIFEST.md` already present under `$Z_HARNESS_PLAN_DIR/`? If so, this is a resume — describe the current MANIFEST state to the user and confirm whether they want to resume or restart.
commands/z-uplift.md:303:MANIFEST_FILES = ["Cargo.toml", "pyproject.toml", "setup.cfg", "package.json"]
commands/z-uplift.md:424:MANIFEST_EXISTS = any(
commands/z-uplift.md:425:    os.path.isfile(os.path.join(repo_root, mf)) for mf in MANIFEST_FILES
commands/z-uplift.md:448:if not MANIFEST_EXISTS:
commands/z-uplift.md:652:### Step 6 — Initialize MANIFEST.md
commands/z-uplift.md:654:Write `$Z_HARNESS_PLAN_DIR/MANIFEST.md` with all confirmed components in `[ ] pending` state:
commands/z-uplift.md:666:    f"# Uplift MANIFEST — {slug}",
commands/z-uplift.md:679:with open(os.path.join(plan_dir, "MANIFEST.md"), "w") as f:
commands/z-uplift.md:681:print("wrote MANIFEST.md")
commands/z-uplift.md:851:Instructions: Examine the source map files for cross-component issues. For each finding, emit an explicit \`component: <slug-from-MANIFEST>\` marker (use the exact slug from the components table, or \`component: global\` for issues spanning all components). Then classify each finding as one of:
commands/z-uplift.md:1160:Insert `<slug>-cross-cutting` as the FIRST row in MANIFEST.md:
commands/z-uplift.md:1163:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_SLUG" "$CROSS_DIR" <<'PYEOF'
commands/z-uplift.md:1184:    print(f"updated existing {cross_slug} row in MANIFEST.md")
commands/z-uplift.md:1193:    print(f"inserted {cross_slug} as first row in MANIFEST.md")
commands/z-uplift.md:1222:Iterate every component in MANIFEST with state `[ ] pending`, **excluding** any row whose slug ends in `-cross-cutting` or whose component column is `(global)` — the synthetic cross-cutting component inserted by Phase 2 (T003) is handled separately in Phase 5 and must not be re-audited here. For each qualifying component, run Steps 1–8 below.
commands/z-uplift.md:1240:### Step 1 — Read MANIFEST and collect pending components
commands/z-uplift.md:1242:Parse MANIFEST.md to collect rows with state `[ ] pending`. Process them in the order they appear (synthetic `<slug>-cross-cutting` is first if present).
commands/z-uplift.md:1245:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" <<'PYEOF'
commands/z-uplift.md:1288:Update the MANIFEST row immediately before any dispatch:
commands/z-uplift.md:1291:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" <<'PYEOF'
commands/z-uplift.md:1565:2. Compute `OTHER_COMP_PATHS` from MANIFEST (all Path-column values except the bailing component and the synthetic cross-cutting row), then run a text-grep to find references:
commands/z-uplift.md:1569:   # Derive OTHER_COMP_PATHS from MANIFEST: all Path-column values except COMP_PATH and cross-cutting synthetic rows
commands/z-uplift.md:1570:   OTHER_COMP_PATHS="$(python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_PATH" <<'INNEREOF'
commands/z-uplift.md:1610:4. Append the dependents warning block to MANIFEST.md's `## Dependents warnings (post-bail)` section (create the section if absent):
commands/z-uplift.md:1613:   python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "$COMP_PATH" "$DEPS_FOUND" <<'PYEOF'
commands/z-uplift.md:1648:5. Mark MANIFEST row as `[!] bailed: crit_high_volume` and populate Audit findings + Bail reason columns:
commands/z-uplift.md:1651:   python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "crit_high_volume" \
commands/z-uplift.md:1753:Update the MANIFEST row's TASKS.md column to `<abs path to COMP_PLAN_DIR/TASKS.md>`.
commands/z-uplift.md:1755:#### Step 2j — Mark `[a] audited` and emit done event
commands/z-uplift.md:1758:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "$COMP_PLAN_DIR/TASKS.md" \
commands/z-uplift.md:1790:    cells[1] = " [a] audited "
commands/z-uplift.md:1814:cp "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-audits.md"
commands/z-uplift.md:1827:### Step 1 — Aggregate queue summary from MANIFEST
commands/z-uplift.md:1829:Parse MANIFEST.md to compute counts:
commands/z-uplift.md:1832:PHASE4_SUMMARY="$(python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$SLUG" <<'PYEOF'
commands/z-uplift.md:1859:    if '[a] audited' in state:
commands/z-uplift.md:1947:> - Dependents warnings: `<DEP_WARN_COUNT>` `<if > 0: note "see MANIFEST.md Dependents warnings section">`
commands/z-uplift.md:1954:cp "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase4-review-gate.md"
commands/z-uplift.md:1969:Parse MANIFEST.md to collect rows with state `[a] audited` **plus** any `[i] implementing` rows (interrupted on a prior invocation). Apply the ordering rule: the synthetic `<slug>-cross-cutting` row is always processed first, regardless of its physical position in the table.
commands/z-uplift.md:1972:IMPL_QUEUE="$(python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$SLUG" <<'PYEOF'
commands/z-uplift.md:1997:    actionable = '[a] audited' in state or '[i] implementing' in state
commands/z-uplift.md:2006:        "implementing": '[i] implementing' in state,
commands/z-uplift.md:2025:#### Step 2a — Handle `[i] implementing` (interrupted resume)
commands/z-uplift.md:2027:If the row state is `[i] implementing` (set on a prior invocation that was interrupted before completion):
commands/z-uplift.md:2031:> Component `<component>` is in state `[i] implementing` — it was being implemented when the last invocation was interrupted.
commands/z-uplift.md:2035:> 2. Mark as done — the implementation was completed manually; update MANIFEST to `[x] done`
commands/z-uplift.md:2036:> 3. Skip — mark as `[s] skipped: user` and move on
commands/z-uplift.md:2044:- **Option 2 (Mark done):** run the manifest_write block from Step 2d with state `[x] done`, emit `component_implement_done` with `outcome: "marked_done_manually"`, continue to the next component.
commands/z-uplift.md:2045:- **Option 3 (Skip):** run the manifest_write block from Step 2d with state `[s] skipped: user`, continue to the next component.
commands/z-uplift.md:2048:#### Step 2b — AskUser gate (normal `[a] audited` components)
commands/z-uplift.md:2050:If the row state was `[a] audited` (not a resume from `[i] implementing`):
commands/z-uplift.md:2083:- **Skip:** run the manifest_write block in Step 2d with state `[s] skipped: user`; continue to next component.
commands/z-uplift.md:2088:Emit `component_implement_start` event and mark MANIFEST `[i] implementing` BEFORE dispatch (so an interrupt is detectable on next resume):
commands/z-uplift.md:2094:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "[i] implementing" <<'PYEOF'
commands/z-uplift.md:2138:Then **exit** the current `/z-uplift` invocation cleanly (do not attempt to wait for `/z-implement-all` inline — it is a separate slash command that the user runs). The next `/z-uplift` invocation will detect the `[i] implementing` row and check completion via Step 2a above.
commands/z-uplift.md:2140:Note: "completion detection" on resume (Step 2a option 2) works as follows — the user can manually mark `[x] done` after `/z-implement-all` finishes, or they can re-invoke with option 1 (Resume) which re-presents the `/z-implement-all` command for any remaining pending tasks.
commands/z-uplift.md:2142:#### Step 2d — MANIFEST state update helper
commands/z-uplift.md:2147:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "<new_state>" <<'PYEOF'
commands/z-uplift.md:2183:Valid `new_state` values used in Phase 5: `[i] implementing`, `[x] done`, `[s] skipped: user`.
commands/z-uplift.md:2189:1. Do NOT modify the current component's MANIFEST row (leave it in `[a] audited` or `[i] implementing`).
commands/z-uplift.md:2190:2. Do NOT modify any subsequent component's MANIFEST row.
commands/z-uplift.md:2217:cp "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase5-implement.md"
z-harness/plans/tiered-quality-uplift/PLAN.md:13:- **D7 MANIFEST.md is the resume authority**; no parallel state file. `--retry-bailed` / `--refresh-component <name>` flags.
z-harness/plans/tiered-quality-uplift/PLAN.md:38:4. **Per-component audit loop** — Phase 3 implementation: per-component output dir scaffolding (`<uplift-slug>-<component-slug>/SPEC.md`, `PLAN.md`), parallel auditor dispatch with STYLE.md (via `rubric_path`) + cross-cutting context injection, bundled consultant critique on REPORT.md, auto-bail check, text-grep dependents reporting, TASKS.md promotion, `reviewer` gate, MANIFEST state updates.
z-harness/plans/tiered-quality-uplift/PLAN.md:39:5. **Implement loop** — Phase 5 implementation: per-component AskUser gates, `/z-implement-all --tasks=` dispatch, MANIFEST state updates, abort handling. Process synthetic `<slug>-cross-cutting` first.
z-harness/plans/tiered-quality-uplift/PLAN.md:40:6. **MANIFEST + telemetry** — MANIFEST.md schema, state machine, resume logic for re-invokes, component-specific telemetry events, `--retry-bailed` / `--refresh-component` flag wiring.
z-harness/plans/tiered-quality-uplift/PLAN.md:43:9. **Smoke test** — run `/z-uplift --no-style --cross-cutting=skip --component scripts` against this repo as a single-component dry run; verify decomposition output, auditor dispatch, REPORT/TASKS generation, MANIFEST state machine.
z-harness/plans/tiered-quality-uplift/PLAN.md:47:- **2026-05-26** (RUN 20260526T030246Z-amend-tiered-quality-uplift) — applied PLAN_AUDIT_REPORT.md blockers + majors. Agent name renames (`z-harness:gemini-consultant` / `codex-consultant` / `codex-reviewer` → `consultant-primary` / `consultant-secondary` / `reviewer`), auditor rubric contract fix (`rubric_path` not inline content), T003 path-computation fix (drop JS regex), T008 skill-pattern retarget (`skills/z-improve/` not missing `z-audit/`), STYLE-gate halt instruction, drop "edit-and-confirm" gate, define entry-file heuristic, `--dimensions` rationale surfaced, T006 `[i] implementing` resume + `--refresh-component` backup, T010 cleanup converted to manual, text-grep dependents labeled incomplete. No new tasks, no completed work disturbed, no consult required.
z-harness/plans/tiered-quality-uplift/TASKS.md:35:- If `global-task` count > 0: compute the sibling synthetic plan dir as `CROSS_DIR="$(dirname "$Z_HARNESS_PLAN_DIR")/${Z_HARNESS_SLUG}-cross-cutting"` (bash) or the python equivalent — do NOT use JS-style `.replace()` regex. Create `$CROSS_DIR/{SPEC.md,PLAN.md,TASKS.md}` (minimal SPEC pointing at CROSS-CUTTING.md; TASKS.md generated one-task-per-G-NNN with aggregated `**Files:**` lines); insert as the FIRST row in MANIFEST.md.
z-harness/plans/tiered-quality-uplift/TASKS.md:46:- For each component in MANIFEST `pending` state (excluding the synthetic `<slug>-cross-cutting` if it exists — that's audited differently, since it's hand-written):
z-harness/plans/tiered-quality-uplift/TASKS.md:47:  - Mark MANIFEST state `[~] auditing` IMMEDIATELY before dispatch (so a mid-audit interrupt is detectable by resume logic). Emit `component_audit_start`.
z-harness/plans/tiered-quality-uplift/TASKS.md:49:  - Extract `per-component-context` rows from CROSS-CUTTING.md whose `component:` marker matches this component's MANIFEST slug exactly (NOT free-text path matching — relies on the explicit slug marker emitted by the cross-cutting consultants in T003).
z-harness/plans/tiered-quality-uplift/TASKS.md:53:  - Count CRITICAL+HIGH and total findings. If `total > 30 OR crit_high > 10`: mark MANIFEST `[!] bailed: crit_high_volume`; write REPORT.md with "BAILED — exceeds /z-audit thresholds" header; run `git grep -l "<component basename>" -- <other component paths>` and append a "Potential dependents (text-grep — incomplete; validate manually for critical APIs)" section to REPORT.md and a `Dependents warnings` section to MANIFEST.md (same incomplete-label); skip TASKS.md generation; emit `component_audit_done` with `bailed: true`; continue.
z-harness/plans/tiered-quality-uplift/TASKS.md:56:  - Mark MANIFEST state `[a] audited`. Emit `component_audit_done`.
z-harness/plans/tiered-quality-uplift/TASKS.md:59:- **Acceptance:** loop iterates components; per-component plan dir is created and structured correctly; auditor dispatch is parallel with bare `subagent_type="auditor"`; `rubric_path` (NOT inline `rubric` content) is passed when dim ∈ {cleanliness, design} and STYLE.md is present, empty otherwise; cross-cutting context is extracted by exact `component:` slug match; bail threshold matches `/z-audit`'s; text-grep dependents section in REPORT.md AND MANIFEST.md carries the "Potential / incomplete" label.
z-harness/plans/tiered-quality-uplift/TASKS.md:66:- Phase 5: process synthetic `<uplift-slug>-cross-cutting` first (if present) THEN components in MANIFEST order with state `[a] audited`:
z-harness/plans/tiered-quality-uplift/TASKS.md:68:  - On proceed: invoke `/z-implement-all --tasks=z-harness/plans/<uplift-slug>-<component-slug>/TASKS.md`. Wait for completion (this is the orchestrator's existing pause point — `/z-implement-all` may itself compaction-pause; resume on next `/z-uplift` invocation picks up the same component if not yet `[x] done`).
z-harness/plans/tiered-quality-uplift/TASKS.md:69:  - Set MANIFEST `[i] implementing` before dispatch, `[x] done` on successful completion (detect by reading the dispatched TASKS.md and confirming all `[ ]` are `[x]`), `[s] skipped: user` on user-skip, leave-as-is on abort.
z-harness/plans/tiered-quality-uplift/TASKS.md:71:- On abort: log `run_end status: aborted_by_user`; exit cleanly. Re-invoke resumes at the same MANIFEST row.
z-harness/plans/tiered-quality-uplift/TASKS.md:74:- **Acceptance:** synthetic cross-cutting component is processed first (or skipped cleanly if absent); per-component AskUser gates work; MANIFEST state transitions are atomic per component; abort leaves remaining MANIFEST rows unchanged.
z-harness/plans/tiered-quality-uplift/TASKS.md:77:### [ ] T006 — MANIFEST.md schema + resume logic + --retry-bailed / --refresh-component flags
z-harness/plans/tiered-quality-uplift/TASKS.md:78:- Implement MANIFEST.md emission at end of Phase 1 (initial state: all rows `[ ] pending`, synthetic `-cross-cutting` row prepended if Phase 2 added it).
z-harness/plans/tiered-quality-uplift/TASKS.md:79:- Resume logic at Setup: parse existing MANIFEST.md (if present); identify next non-terminal state; jump to corresponding phase. Branches:
z-harness/plans/tiered-quality-uplift/TASKS.md:81:  - any `[i] implementing` row (mid-implement interrupt) → AskUser per SPEC L237: resume `/z-implement-all` for this component / mark `[x] done` (user finished manually) / mark `[s] skipped` / abort uplift. Apply the chosen transition, then resume Phase 5 at the next row.
z-harness/plans/tiered-quality-uplift/TASKS.md:82:  - all rows `[a] audited` or terminal → Phase 5.
z-harness/plans/tiered-quality-uplift/TASKS.md:86:- Atomic MANIFEST.md updates: read full file, mutate target row, write via tmpfile + `os.replace`.
z-harness/plans/tiered-quality-uplift/TASKS.md:89:- **Acceptance:** MANIFEST table updates row-by-row without corruption under simulated interrupts; resume detection covers all three branches above (including the `[i] implementing` AskUser branch); `--refresh-component` produces a populated `<plan-dir>/archive/<RUN>/refreshed/<component-slug>/` containing the pre-refresh REPORT.md and TASKS.md before deletion; both flags mutate only the targeted rows.
z-harness/plans/tiered-quality-uplift/TASKS.md:105:- Create `docs/human/z-uplift.md`: 2-3 paragraphs covering what it does, when to use it vs `/z-audit` and `/z-mr-review`, the STYLE.md prerequisite, how to interpret MANIFEST states. Cite `commands/z-uplift.md:<line>` for the key phases.
z-harness/plans/tiered-quality-uplift/TASKS.md:138:  - Phase 5: AskUser per component fires; user picks "skip" to avoid actually modifying code in the smoke test; MANIFEST shows `[s] skipped: user` for scripts.
z-harness/plans/tiered-quality-uplift/TASKS.md:139:  - Cleanup: DO NOT auto-delete the smoke test plan dir. The user inspects `events.jsonl`, MANIFEST, REPORT.md after the run. Manual cleanup when done: `rm -rf z-harness/plans/tiered-quality-uplift-smoke-*`.
z-harness/plans/tiered-quality-uplift/TASKS.md:143:- **Acceptance:** all phases execute, all expected events appear in `archive/<RUN>/events.jsonl`, MANIFEST transitions correctly, no exceptions or unhandled error paths.
z-harness/plans/tiered-quality-uplift/PLAN_AUDIT_REPORT.md:9:The plan is structurally sound: zero new agents, sibling-plan layout reuses `/z-implement-all --tasks=` verbatim, MANIFEST as resume authority. The core orchestration design is buildable as-is. However, several **reality-check blockers** would cause the implementation to fail at dispatch time. These are concentrated in TASKS T003 / T004 / T008 and the SPEC dispatch sections. Fix four blockers and six majors before implementation; minors can be polished during T001–T008.
z-harness/plans/tiered-quality-uplift/PLAN_AUDIT_REPORT.md:69:**Evidence:** T010 is INTERACTIVE but auto-cleans the plan dir post-run. User wanting to inspect `events.jsonl`, MANIFEST, REPORT loses them.
z-harness/plans/tiered-quality-uplift/PLAN_AUDIT_REPORT.md:77:### MAJOR — `[i] implementing` resume branch missing from T006 acceptance
z-harness/plans/tiered-quality-uplift/PLAN_AUDIT_REPORT.md:81:**Evidence:** The state machine in SPEC.md L158 includes `[i] implementing`; SPEC L237 enumerates the AskUser branch (resume / mark-done / mark-skipped / abort). T006's acceptance only enumerates `[~] auditing` and `[a] audited` cases. The implementer could derive from SPEC L237, but the acceptance gap risks silent omission.
z-harness/plans/tiered-quality-uplift/PLAN_AUDIT_REPORT.md:83:**Recommendation:** Add T006 acceptance bullet: "Resume detects `[i] implementing` and runs the SPEC L237 AskUser branch."
z-harness/plans/tiered-quality-uplift/PLAN_AUDIT_REPORT.md:123:**Recommendation:** Update label in REPORT.md and MANIFEST.md to "Potential dependents (text-grep — incomplete; validate manually for critical APIs)".
z-harness/plans/tiered-quality-uplift/PLAN_AUDIT_REPORT.md:141:**Recommendation:** Require cross-cutting consultant to emit explicit `component: <slug>` markers (already in CROSS-CUTTING.md schema implicitly via "affects `<component-name>`"). Strengthen T004 to match on exact slug from MANIFEST, not prose.
z-harness/plans/tiered-quality-uplift/PLAN_AUDIT_REPORT.md:151:**Recommendation:** Add SPEC invariant: "Only one `/z-uplift` invocation per repo at a time; concurrent invocations race on MANIFEST.md."
z-harness/plans/tiered-quality-uplift/PLAN_AUDIT_REPORT.md:178:  - "[i] implementing resume" classification → Codex BLOCKER, Gemini BLOCKER → settled as **MAJOR** (SPEC L237 already enumerates behavior; the gap is in T006 acceptance, not in the design).
z-harness/plans/tiered-quality-uplift/PLAN_AUDIT_REPORT.md:195:   - Add T006 resume branch for `[i] implementing`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff-v1.patch:40:Check for an existing slug dir in the canonical plans directory (`z-harness/plans/`). If a MANIFEST.md is found there, this is a **resume** — skip decomposition phases and jump to the next non-terminal MANIFEST state. If only a slug collision without MANIFEST, prompt the user to confirm or choose a different slug.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff-v1.patch:168:- Is there a `MANIFEST.md` already present under `$Z_HARNESS_PLAN_DIR/`? If so, this is a resume — describe the current MANIFEST state to the user and confirm whether they want to resume or restart.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff-v1.patch:193:After confirmation, initialize `MANIFEST.md` with all components in `[ ] pending` state.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff-v1.patch:214:If any `global-task` findings exist, create a synthetic component named `<slug>-cross-cutting` and insert it FIRST in MANIFEST.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff-v1.patch:226:For each component in MANIFEST `pending` state (processing synthetic `<slug>-cross-cutting` first if it exists):
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff-v1.patch:228:1. Mark MANIFEST state `[~] auditing` immediately before dispatch.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff-v1.patch:229:2. Dispatch one `auditor` subagent per `--dimensions` value in parallel. Inject `rubric_path` (absolute path of `./STYLE.md`) for `cleanliness` and `design` dimensions when STYLE.md is present and `NO_STYLE` is not set. Inject `cross_cutting_context` from CROSS-CUTTING.md entries matching this component's MANIFEST slug (exact match).
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff-v1.patch:232:5. Auto-bail check: if `>10 CRIT-HIGH` OR `>30 total` findings → mark MANIFEST `[!] bailed: crit_high_volume`; run `git grep -l "<component-basename>"` across other components; append "Potential dependents (text-grep — incomplete; validate manually for critical APIs)" to REPORT.md and MANIFEST.md; skip TASKS.md generation; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff-v1.patch:235:8. Mark MANIFEST state `[a] audited`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff-v1.patch:267:For each component with state `[a] audited` in MANIFEST order (synthetic `<slug>-cross-cutting` first):
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff-v1.patch:270:2. If proceed: mark MANIFEST `[i] implementing`; invoke `/z-implement-all --tasks=z-harness/plans/<slug>-<component>/TASKS.md`; wait for completion; mark MANIFEST `[x] done`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff-v1.patch:271:3. If skip: mark MANIFEST `[s] skipped: user`; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff-v1.patch:274:On re-invoke with a component in `[i] implementing` state (interrupted mid-implement): AskUser — resume with `/z-implement-all` on this component / mark `[s] skipped` / mark `[x] done` (if completed manually) / abort.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/decisions.md:12:  - (c) `z-harness/plans/<slug>-<comp>/{REPORT.md,TASKS.md,SPEC.md,PLAN.md}` — each component is its own full sibling plan, uplift writes a parent MANIFEST.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/decisions.md:13:- **Tentative call:** (c). `/z-implement-all --tasks=<path>` derives `$BASE` from the tasks file's parent dir and reads SPEC/PLAN from `$BASE`. Option (a) would force a shared SPEC/PLAN at the uplift root, which doesn't match (each component has its own scope). Option (c) keeps each component a self-contained, resumable, archive-able plan. Parent `<slug>/MANIFEST.md` lists children.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/decisions.md:46:  - (a) Inherit verbatim — components exceeding the threshold get auto-promoted from "audit" to "needs full /z-plan" in MANIFEST.md and skipped from the implement queue.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/decisions.md:64:  - (a) MANIFEST.md is the authority: parses `[ ]`/`[x]`/`[skip]` per component-stage (decompose / cross-cutting / audit / implement). On re-invoke, finds next pending stage; skips completed ones.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/decisions.md:66:  - (c) Both — MANIFEST for human; state file for fast machine fast-forward.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/decisions.md:67:- **Tentative call:** (a). MANIFEST is already the durable record of progress; a parallel JSON file is duplicate state with drift risk. The harness convention is "the artifact is the state" — TASKS.md `[x]` count is the durable record for `/z-implement-all`.
z-harness/plans/tiered-quality-uplift/archive/20260526T025504Z-tiered-quality-uplift-audit-plan/PLAN_AUDIT_REPORT.md:9:The plan is structurally sound: zero new agents, sibling-plan layout reuses `/z-implement-all --tasks=` verbatim, MANIFEST as resume authority. The core orchestration design is buildable as-is. However, several **reality-check blockers** would cause the implementation to fail at dispatch time. These are concentrated in TASKS T003 / T004 / T008 and the SPEC dispatch sections. Fix four blockers and six majors before implementation; minors can be polished during T001–T008.
z-harness/plans/tiered-quality-uplift/archive/20260526T025504Z-tiered-quality-uplift-audit-plan/PLAN_AUDIT_REPORT.md:69:**Evidence:** T010 is INTERACTIVE but auto-cleans the plan dir post-run. User wanting to inspect `events.jsonl`, MANIFEST, REPORT loses them.
z-harness/plans/tiered-quality-uplift/archive/20260526T025504Z-tiered-quality-uplift-audit-plan/PLAN_AUDIT_REPORT.md:77:### MAJOR — `[i] implementing` resume branch missing from T006 acceptance
z-harness/plans/tiered-quality-uplift/archive/20260526T025504Z-tiered-quality-uplift-audit-plan/PLAN_AUDIT_REPORT.md:81:**Evidence:** The state machine in SPEC.md L158 includes `[i] implementing`; SPEC L237 enumerates the AskUser branch (resume / mark-done / mark-skipped / abort). T006's acceptance only enumerates `[~] auditing` and `[a] audited` cases. The implementer could derive from SPEC L237, but the acceptance gap risks silent omission.
z-harness/plans/tiered-quality-uplift/archive/20260526T025504Z-tiered-quality-uplift-audit-plan/PLAN_AUDIT_REPORT.md:83:**Recommendation:** Add T006 acceptance bullet: "Resume detects `[i] implementing` and runs the SPEC L237 AskUser branch."
z-harness/plans/tiered-quality-uplift/archive/20260526T025504Z-tiered-quality-uplift-audit-plan/PLAN_AUDIT_REPORT.md:123:**Recommendation:** Update label in REPORT.md and MANIFEST.md to "Potential dependents (text-grep — incomplete; validate manually for critical APIs)".
z-harness/plans/tiered-quality-uplift/archive/20260526T025504Z-tiered-quality-uplift-audit-plan/PLAN_AUDIT_REPORT.md:141:**Recommendation:** Require cross-cutting consultant to emit explicit `component: <slug>` markers (already in CROSS-CUTTING.md schema implicitly via "affects `<component-name>`"). Strengthen T004 to match on exact slug from MANIFEST, not prose.
z-harness/plans/tiered-quality-uplift/archive/20260526T025504Z-tiered-quality-uplift-audit-plan/PLAN_AUDIT_REPORT.md:151:**Recommendation:** Add SPEC invariant: "Only one `/z-uplift` invocation per repo at a time; concurrent invocations race on MANIFEST.md."
z-harness/plans/tiered-quality-uplift/archive/20260526T025504Z-tiered-quality-uplift-audit-plan/PLAN_AUDIT_REPORT.md:178:  - "[i] implementing resume" classification → Codex BLOCKER, Gemini BLOCKER → settled as **MAJOR** (SPEC L237 already enumerates behavior; the gap is in T006 acceptance, not in the design).
z-harness/plans/tiered-quality-uplift/archive/20260526T025504Z-tiered-quality-uplift-audit-plan/PLAN_AUDIT_REPORT.md:195:   - Add T006 resume branch for `[i] implementing`.
z-harness/plans/tiered-quality-uplift/archive/20260526T025504Z-tiered-quality-uplift-audit-plan/phase2-design.md:20:- **MANIFEST state machine has 6 states + 2 reason-bearing variants.** Acceptable; each maps to a distinct UX moment. No simplification recommended.
z-harness/plans/tiered-quality-uplift/archive/20260526T025504Z-tiered-quality-uplift-audit-plan/phase2-design.md:31:- MANIFEST.md as sole authority + atomic rewrites (read full → mutate → tmpfile → `os.replace`) is the right pattern. T006 calls it out explicitly. Two interrupting `/z-uplift` invocations would race on MANIFEST — out of scope but worth one-line note "only one /z-uplift per repo at a time" in SPEC.
z-harness/plans/tiered-quality-uplift/archive/20260526T025504Z-tiered-quality-uplift-audit-plan/phase2-design.md:32:- Cross-cutting `global-task` runs FIRST in MANIFEST — addresses the Gemini-flagged build-break risk from the earlier consult. Sound.
z-harness/plans/tiered-quality-uplift/archive/20260526T025504Z-tiered-quality-uplift-audit-plan/phase2-design.md:50:4. **Add "only one /z-uplift per repo at a time" guard or note** — MANIFEST race prevention.
z-harness/plans/tiered-quality-uplift/archive/20260526T025504Z-tiered-quality-uplift-audit-plan/phase1-reality.md:52:## MAJOR — MANIFEST resume logic does not enumerate `[i] implementing`
z-harness/plans/tiered-quality-uplift/archive/20260526T025504Z-tiered-quality-uplift-audit-plan/phase1-reality.md:54:T006 acceptance only handles `[~] auditing` and `[a] audited`. The state machine includes `[i] implementing` (active interrupt-time state). The edge-cases section in SPEC L237 references this case but no T006 acceptance bullet describes the resume branch. Risk: re-invoke after Ctrl-C during `/z-implement-all` jumps to the wrong phase.
z-harness/plans/tiered-quality-uplift/archive/20260526T025504Z-tiered-quality-uplift-audit-plan/phase1-reality.md:56:**Fix:** in T006, enumerate `[i] implementing` as a separate resume branch (AskUser: resume implement / mark done / mark skipped / abort, per SPEC L237).
z-harness/plans/tiered-quality-uplift/archive/20260526T025504Z-tiered-quality-uplift-audit-plan/phase1-reality.md:66:T010 says "delete the smoke test plan dir after verification" with the task marked INTERACTIVE. Sequence risk: the orchestrator may auto-clean before the user actually inspects events.jsonl, MANIFEST.md, etc.
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:73:Check for an existing slug dir in the canonical plans directory (`z-harness/plans/`). If a MANIFEST.md is found there, this is a **resume** — skip decomposition phases and jump to the next non-terminal MANIFEST state. If only a slug collision without MANIFEST, prompt the user to confirm or choose a different slug.
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:221:- Is there a `MANIFEST.md` already present under `$Z_HARNESS_PLAN_DIR/`? If so, this is a resume — describe the current MANIFEST state to the user and confirm whether they want to resume or restart.
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:303:MANIFEST_FILES = ["Cargo.toml", "pyproject.toml", "setup.cfg", "package.json"]
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:424:MANIFEST_EXISTS = any(
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:425:    os.path.isfile(os.path.join(repo_root, mf)) for mf in MANIFEST_FILES
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:448:if not MANIFEST_EXISTS:
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:652:### Step 6 — Initialize MANIFEST.md
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:654:Write `$Z_HARNESS_PLAN_DIR/MANIFEST.md` with all confirmed components in `[ ] pending` state:
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:666:    f"# Uplift MANIFEST — {slug}",
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:679:with open(os.path.join(plan_dir, "MANIFEST.md"), "w") as f:
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:681:print("wrote MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:851:Instructions: Examine the source map files for cross-component issues. For each finding, emit an explicit \`component: <slug-from-MANIFEST>\` marker (use the exact slug from the components table, or \`component: global\` for issues spanning all components). Then classify each finding as one of:
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1160:Insert `<slug>-cross-cutting` as the FIRST row in MANIFEST.md:
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1163:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_SLUG" "$CROSS_DIR" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1184:    print(f"updated existing {cross_slug} row in MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1193:    print(f"inserted {cross_slug} as first row in MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1222:Iterate every component in MANIFEST with state `[ ] pending` (the synthetic `<slug>-cross-cutting` component, if present, was already inserted at the top of MANIFEST by Phase 2 and is also processed here as a regular `pending` row — it is NOT skipped; its TASKS.md already exists, so Step 6 below is skipped for it). For each such component, run Steps 1–8 below.
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1240:### Step 1 — Read MANIFEST and collect pending components
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1242:Parse MANIFEST.md to collect rows with state `[ ] pending`. Process them in the order they appear (synthetic `<slug>-cross-cutting` is first if present).
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1245:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1283:Update the MANIFEST row immediately before any dispatch:
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1286:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1559:   # OTHER_COMP_PATHS is the space-separated list of all non-current component paths from MANIFEST
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1575:4. Append the dependents warning block to MANIFEST.md's `## Dependents warnings (post-bail)` section (create the section if absent):
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1578:   python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "$COMP_PATH" "$DEPS_FOUND" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1608:5. Mark MANIFEST row as `[!] bailed: crit_high_volume`:
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1611:   python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "crit_high_volume" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1688:Update the MANIFEST row's TASKS.md column to `<abs path to COMP_PLAN_DIR/TASKS.md>`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1690:#### Step 2j — Mark `[a] audited` and emit done event
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1693:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "$COMP_PLAN_DIR/TASKS.md" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1703:# Update state cell: [~] auditing → [a] audited
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1708:updated = pattern.sub(r'\1[a] audited\2', content, count=1)
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1732:cp "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-audits.md"
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1765:For each component with state `[a] audited` in MANIFEST order (synthetic `<slug>-cross-cutting` first):
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1768:2. If proceed: mark MANIFEST `[i] implementing`; invoke `/z-implement-all --tasks=z-harness/plans/<slug>-<component>/TASKS.md`; wait for completion; mark MANIFEST `[x] done`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1769:3. If skip: mark MANIFEST `[s] skipped: user`; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff-v1.patch:1772:On re-invoke with a component in `[i] implementing` state (interrupted mid-implement): AskUser — resume with `/z-implement-all` on this component / mark `[s] skipped` / mark `[x] done` (if completed manually) / abort.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:34:- If `global-task` count > 0: create `$Z_HARNESS_PLAN_DIR.replace(/<slug>$/, '<slug>-cross-cutting')/{SPEC.md,PLAN.md,TASKS.md}` (minimal SPEC pointing at CROSS-CUTTING.md; TASKS.md generated one-task-per-G-NNN with aggregated `**Files:**` lines); insert as the FIRST row in MANIFEST.md.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:44:- For each component in MANIFEST `pending` state (excluding the synthetic `<slug>-cross-cutting` if it exists — that's audited differently, since it's hand-written):
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:45:  - Mark MANIFEST state `[~] auditing`. Emit `component_audit_start`.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:51:  - Count CRITICAL+HIGH and total findings. If `total > 30 OR crit_high > 10`: mark MANIFEST `[!] bailed: crit_high_volume`; write REPORT.md with "BAILED — exceeds /z-audit thresholds" header; run `git grep -l "<component basename>" -- <other component paths>` and append "Dependents (text-grep):" section to REPORT.md and a `Dependents warnings` section to MANIFEST.md; skip TASKS.md generation; emit `component_audit_done` with `bailed: true`; continue.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:54:  - Mark MANIFEST state `[a] audited`. Emit `component_audit_done`.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:63:- Phase 5: process synthetic `<uplift-slug>-cross-cutting` first (if present) THEN components in MANIFEST order with state `[a] audited`:
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:65:  - On proceed: invoke `/z-implement-all --tasks=z-harness/plans/<uplift-slug>-<component-slug>/TASKS.md`. Wait for completion (this is the orchestrator's existing pause point — `/z-implement-all` may itself compaction-pause; resume on next `/z-uplift` invocation picks up the same component if not yet `[x] done`).
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:66:  - Set MANIFEST `[i] implementing` before dispatch, `[x] done` on successful completion (detect by reading the dispatched TASKS.md and confirming all `[ ]` are `[x]`), `[s] skipped: user` on user-skip, leave-as-is on abort.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:68:- On abort: log `run_end status: aborted_by_user`; exit cleanly. Re-invoke resumes at the same MANIFEST row.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:71:- **Acceptance:** synthetic cross-cutting component is processed first (or skipped cleanly if absent); per-component AskUser gates work; MANIFEST state transitions are atomic per component; abort leaves remaining MANIFEST rows unchanged.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:74:### [ ] T006 — MANIFEST.md schema + resume logic + --retry-bailed / --refresh-component flags
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:75:- Implement MANIFEST.md emission at end of Phase 1 (initial state: all rows `[ ] pending`, synthetic `-cross-cutting` row prepended if Phase 2 added it).
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:76:- Resume logic at Setup: parse existing MANIFEST.md (if present); identify next non-terminal state; jump to corresponding phase (audit if any `[ ] pending` or `[~] auditing` rows; implement if all are `[a] audited` or terminal). Emit `resume_detected` event.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:79:- Atomic MANIFEST.md updates: read full file, mutate target row, write via tmpfile + `os.replace`.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:82:- **Acceptance:** MANIFEST table updates row-by-row without corruption under simulated interrupts; resume detection works (delete a `[a] audited` row's TASKS.md and re-invoke → Phase 5 still picks it up; mark `[~] auditing` and re-invoke → Phase 3 redoes it); both flags mutate only the targeted rows.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:98:- Create `docs/human/z-uplift.md`: 2-3 paragraphs covering what it does, when to use it vs `/z-audit` and `/z-mr-review`, the STYLE.md prerequisite, how to interpret MANIFEST states. Cite `commands/z-uplift.md:<line>` for the key phases.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:131:  - Phase 5: AskUser per component fires; user picks "skip" to avoid actually modifying code in the smoke test; MANIFEST shows `[s] skipped: user` for scripts.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/TASKS.md:136:- **Acceptance:** all phases execute, all expected events appear in `archive/<RUN>/events.jsonl`, MANIFEST transitions correctly, no exceptions or unhandled error paths.
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:73:Check for an existing slug dir in the canonical plans directory (`z-harness/plans/`). If a MANIFEST.md is found there, this is a **resume** — skip decomposition phases and jump to the next non-terminal MANIFEST state. If only a slug collision without MANIFEST, prompt the user to confirm or choose a different slug.
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:221:- Is there a `MANIFEST.md` already present under `$Z_HARNESS_PLAN_DIR/`? If so, this is a resume — describe the current MANIFEST state to the user and confirm whether they want to resume or restart.
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:303:MANIFEST_FILES = ["Cargo.toml", "pyproject.toml", "setup.cfg", "package.json"]
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:424:MANIFEST_EXISTS = any(
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:425:    os.path.isfile(os.path.join(repo_root, mf)) for mf in MANIFEST_FILES
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:448:if not MANIFEST_EXISTS:
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:652:### Step 6 — Initialize MANIFEST.md
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:654:Write `$Z_HARNESS_PLAN_DIR/MANIFEST.md` with all confirmed components in `[ ] pending` state:
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:666:    f"# Uplift MANIFEST — {slug}",
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:679:with open(os.path.join(plan_dir, "MANIFEST.md"), "w") as f:
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:681:print("wrote MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:827:Instructions: Examine the source map files for cross-component issues. For each finding, emit an explicit \`component: <slug-from-MANIFEST>\` marker (use the exact slug from the components table, or \`component: global\` for issues spanning all components). Then classify each finding as one of:
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:954:Insert `<slug>-cross-cutting` as the FIRST row in MANIFEST.md:
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:957:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_SLUG" "$CROSS_DIR" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:979:print(f"inserted {cross_slug} as first row in MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:1007:For each component in MANIFEST `pending` state (processing synthetic `<slug>-cross-cutting` first if it exists):
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:1009:1. Mark MANIFEST state `[~] auditing` immediately before dispatch.
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:1010:2. Dispatch one `auditor` subagent per `--dimensions` value in parallel. Inject `rubric_path` (absolute path of `./STYLE.md`) for `cleanliness` and `design` dimensions when STYLE.md is present and `NO_STYLE` is not set. Inject `cross_cutting_context` from CROSS-CUTTING.md entries matching this component's MANIFEST slug (exact match).
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:1013:5. Auto-bail check: if `>10 CRIT-HIGH` OR `>30 total` findings → mark MANIFEST `[!] bailed: crit_high_volume`; run `git grep -l "<component-basename>"` across other components; append "Potential dependents (text-grep — incomplete; validate manually for critical APIs)" to REPORT.md and MANIFEST.md; skip TASKS.md generation; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:1016:8. Mark MANIFEST state `[a] audited`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:1048:For each component with state `[a] audited` in MANIFEST order (synthetic `<slug>-cross-cutting` first):
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:1051:2. If proceed: mark MANIFEST `[i] implementing`; invoke `/z-implement-all --tasks=z-harness/plans/<slug>-<component>/TASKS.md`; wait for completion; mark MANIFEST `[x] done`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:1052:3. If skip: mark MANIFEST `[s] skipped: user`; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch:1055:On re-invoke with a component in `[i] implementing` state (interrupted mid-implement): AskUser — resume with `/z-implement-all` on this component / mark `[s] skipped` / mark `[x] done` (if completed manually) / abort.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/phase3-decisions-final.md:9:- `global-task` — needs its own plan; surfaces as a dedicated component slot in MANIFEST (`<slug>-cross-cutting/`).
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/phase3-decisions-final.md:31:### A5 — Explicit bail states in MANIFEST (Codex)
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/phase3-decisions-final.md:32:MANIFEST.md component states are:
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/phase3-decisions-final.md:33:- `[ ] pending` / `[~] auditing` / `[a] audited` / `[i] implementing` / `[x] done`
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/phase3-decisions-final.md:35:- `[s] skipped: <reason>` (user explicitly excluded)
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/phase3-decisions-final.md:40:`/z-uplift` is incremental. Re-running picks up at the next `pending` MANIFEST entry. Flags:
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/phase3-decisions-final.md:50:Path-derived slugs cover 95% of cases. Duplicate-package-name collisions across nested dirs are rare; collision detection at decomposition time (A2) handles them with a one-time AskUser disambiguation. A parallel ID system adds permanent complexity to MANIFEST for a rare case.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/phase3-decisions-final.md:54:- D5 (auto-bail thresholds), D6 (sequential implement with gates), D7 (MANIFEST is the resume authority — extended per A5/A6), D8 (name = `/z-uplift`).
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:34:- **Phase 2 — Cross-cutting pass** — dispatch `gemini-consultant` + `codex-consultant` in parallel on a curated source map AND STYLE.md (if present); merge findings into `CROSS-CUTTING.md` with three-tier classification (`global-task` / `per-component-context` / `risk`). Style-drift findings are explicitly called out (cite STYLE.md rule IDs). `global-task` items become a synthetic component named `<slug>-cross-cutting` inserted FIRST in MANIFEST.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:35:- **Phase 3 — Per-component audits** — for each component in MANIFEST order: dispatch `auditor` agents per dimension in parallel (mirroring `/z-audit` Phases 2–6 inline); inject STYLE.md as the authoritative rubric for `cleanliness` and `design` dimensions (if STYLE.md present); read CROSS-CUTTING.md `per-component-context` entries as additional input; produce per-component `REPORT.md` + `TASKS.md` in sibling plan dir `z-harness/plans/<slug>-<component>/`; inherit `/z-audit`'s >30-findings / >10-CRIT-HIGH auto-bail; on bail, run cheap text-grep across other components for the bailed component's symbols/paths and warn user. Update MANIFEST per-component state after each.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:37:- **Phase 5 — Sequential implement** — for each non-bailed component in MANIFEST order: AskUser gate (proceed / skip / abort); invoke `/z-implement-all --tasks=z-harness/plans/<slug>-<component>/TASKS.md`; update MANIFEST state to `[x] done` on success.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:54:├── MANIFEST.md                                      ← component table + state (resume authority)
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:116:If `global-task` count > 0 → synthetic component `<slug>-cross-cutting` inserted at top of MANIFEST. Its TASKS.md is hand-written from `global-task` entries (one task per G-NNN), with `**Files:**` lines aggregating affected paths.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:119:For each component in MANIFEST `pending` state:
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:120:1. Mark MANIFEST state `[~] auditing`.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:124:5. Auto-bail check: count CRITICAL+HIGH and total findings. If >10 CRIT-HIGH OR >30 total → mark MANIFEST `[!] bailed: crit_high_volume` (or `bailed: spec_problem` for STATUS: spec_problem from auditor); write partial REPORT.md; run cheap text-grep `git grep -l "<component-basename>"` across other components, append "Dependents (text-grep):" section to REPORT.md; skip TASKS.md generation; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:127:8. Mark MANIFEST state `[a] audited`.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:130:For each component with state `[a] audited`:
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:133:3. On completion: mark MANIFEST `[x] done`.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:134:4. On user-skip: mark MANIFEST `[s] skipped: user`.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:135:5. On abort: mark MANIFEST state for this and remaining components left unchanged; log `run_end status: aborted_by_user`; exit.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:139:### `commands/z-uplift.md` — MANIFEST.md shape
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:141:# Uplift MANIFEST — <slug>
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:149:| [x] done | <slug>-cross-cutting | (global) | 4 (2 HIGH) | — | z-harness/plans/<slug>-cross-cutting/TASKS.md |
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:150:| [a] audited | crates/foo | foo | 8 (1 HIGH) | — | z-harness/plans/<slug>-foo/TASKS.md |
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:158:States: `[ ] pending` `[~] auditing` `[a] audited` `[i] implementing` `[x] done` `[!] bailed: <reason>` `[s] skipped: <reason>`.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:160:Resume: on re-invoke, orchestrator parses MANIFEST, identifies next non-terminal state, resumes at the matching phase (audit or implement). `--retry-bailed` and `--refresh-component <name>` mutate states accordingly.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:202:- MANIFEST.md is the resume authority; no parallel state file.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:203:- Components processed sequentially in MANIFEST order; synthetic `-cross-cutting` first if it exists.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:223:- Idempotent: re-invoking `/z-uplift` with no flags resumes at the next non-terminal MANIFEST state.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:236:- All components bail → MANIFEST shows nothing in `[a] audited` state; Phase 5 has nothing to do; recommend user run `/z-plan` on the bailed components individually.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/SPEC.md:237:- User re-invokes mid-implement (Ctrl-C during Phase 5) → MANIFEST shows last component `[i] implementing`. Re-invoke detects this, asks user: resume with `/z-implement-all` on this component / mark `[s] skipped` / mark `[x] done` (if they finished manually) / abort.
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/delta-v2.patch:7:-Iterate every component in MANIFEST with state `[ ] pending` (the synthetic `<slug>-cross-cutting` component, if present, was already inserted at the top of MANIFEST by Phase 2 and is also processed here as a regular `pending` row — it is NOT skipped; its TASKS.md already exists, so Step 6 below is skipped for it). For each such component, run Steps 1–8 below.
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/delta-v2.patch:8:+Iterate every component in MANIFEST with state `[ ] pending`, **excluding** any row whose slug ends in `-cross-cutting` or whose component column is `(global)` — the synthetic cross-cutting component inserted by Phase 2 (T003) is handled separately in Phase 5 and must not be re-audited here. For each qualifying component, run Steps 1–8 below.
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/delta-v2.patch:34: python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/delta-v2.patch:62:+2. Compute `OTHER_COMP_PATHS` from MANIFEST (all Path-column values except the bailing component and the synthetic cross-cutting row), then run a text-grep to find references:
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/delta-v2.patch:66:-   # OTHER_COMP_PATHS is the space-separated list of all non-current component paths from MANIFEST
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/delta-v2.patch:67:+   # Derive OTHER_COMP_PATHS from MANIFEST: all Path-column values except COMP_PATH and cross-cutting synthetic rows
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/delta-v2.patch:68:+   OTHER_COMP_PATHS="$(python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_PATH" <<'INNEREOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/delta-v2.patch:99:    python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "$COMP_PATH" "$DEPS_FOUND" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/delta-v2.patch:122:-5. Mark MANIFEST row as `[!] bailed: crit_high_volume`:
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/delta-v2.patch:123:+5. Mark MANIFEST row as `[!] bailed: crit_high_volume` and populate Audit findings + Bail reason columns:
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/delta-v2.patch:126:-   python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "crit_high_volume" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/delta-v2.patch:128:+   python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "crit_high_volume" \
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/delta-v2.patch:178: #### Step 2j — Mark `[a] audited` and emit done event
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/delta-v2.patch:181:-python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "$COMP_PLAN_DIR/TASKS.md" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/delta-v2.patch:183:+python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "$COMP_PLAN_DIR/TASKS.md" \
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/delta-v2.patch:202:-# Update state cell: [~] auditing → [a] audited
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/delta-v2.patch:216:+    cells[1] = " [a] audited "
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/delta-v2.patch:227:-updated = pattern.sub(r'\1[a] audited\2', content, count=1)
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/delta-from-T002.patch:23:-If any `global-task` findings exist, create a synthetic component named `<slug>-cross-cutting` and insert it FIRST in MANIFEST.
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/delta-from-T002.patch:144:+Instructions: Examine the source map files for cross-component issues. For each finding, emit an explicit \`component: <slug-from-MANIFEST>\` marker (use the exact slug from the components table, or \`component: global\` for issues spanning all components). Then classify each finding as one of:
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/delta-from-T002.patch:271:+Insert `<slug>-cross-cutting` as the FIRST row in MANIFEST.md:
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/delta-from-T002.patch:274:+python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_SLUG" "$CROSS_DIR" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/delta-from-T002.patch:296:+print(f"inserted {cross_slug} as first row in MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/PLAN.md:13:- **D7 MANIFEST.md is the resume authority**; no parallel state file. `--retry-bailed` / `--refresh-component <name>` flags.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/PLAN.md:38:4. **Per-component audit loop** — Phase 3 implementation: per-component output dir scaffolding (`<uplift-slug>-<component-slug>/SPEC.md`, `PLAN.md`), parallel auditor dispatch with STYLE.md + cross-cutting context injection, bundled consultant critique on REPORT.md, auto-bail check, text-grep dependents reporting, TASKS.md promotion, codex-reviewer gate, MANIFEST state updates.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/PLAN.md:39:5. **Implement loop** — Phase 5 implementation: per-component AskUser gates, `/z-implement-all --tasks=` dispatch, MANIFEST state updates, abort handling. Process synthetic `<slug>-cross-cutting` first.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/PLAN.md:40:6. **MANIFEST + telemetry** — MANIFEST.md schema, state machine, resume logic for re-invokes, component-specific telemetry events, `--retry-bailed` / `--refresh-component` flag wiring.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/PLAN.md:43:9. **Smoke test** — run `/z-uplift --no-style --cross-cutting=skip --component scripts` against this repo as a single-component dry run; verify decomposition output, auditor dispatch, REPORT/TASKS generation, MANIFEST state machine.
z-harness/plans/tiered-quality-uplift/archive/20260526T020417Z-tiered-quality-uplift/phase1-context.md:19:- Top-level MANIFEST.md tracks component status (audited / implemented / skipped).
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/delta-v2.patch:355:+    print(f"updated existing {cross_slug} row in MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/delta-v2.patch:364:+    print(f"inserted {cross_slug} as first row in MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/delta-v2.patch:368:-print(f"inserted {cross_slug} as first row in MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff.patch:40:Check for an existing slug dir in the canonical plans directory (`z-harness/plans/`). If a MANIFEST.md is found there, this is a **resume** — skip decomposition phases and jump to the next non-terminal MANIFEST state. If only a slug collision without MANIFEST, prompt the user to confirm or choose a different slug.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff.patch:188:- Is there a `MANIFEST.md` already present under `$Z_HARNESS_PLAN_DIR/`? If so, this is a resume — describe the current MANIFEST state to the user and confirm whether they want to resume or restart.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff.patch:213:After confirmation, initialize `MANIFEST.md` with all components in `[ ] pending` state.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff.patch:234:If any `global-task` findings exist, create a synthetic component named `<slug>-cross-cutting` and insert it FIRST in MANIFEST.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff.patch:246:For each component in MANIFEST `pending` state (processing synthetic `<slug>-cross-cutting` first if it exists):
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff.patch:248:1. Mark MANIFEST state `[~] auditing` immediately before dispatch.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff.patch:249:2. Dispatch one `auditor` subagent per `--dimensions` value in parallel. Inject `rubric_path` (absolute path of `./STYLE.md`) for `cleanliness` and `design` dimensions when STYLE.md is present and `NO_STYLE` is not set. Inject `cross_cutting_context` from CROSS-CUTTING.md entries matching this component's MANIFEST slug (exact match).
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff.patch:252:5. Auto-bail check: if `>10 CRIT-HIGH` OR `>30 total` findings → mark MANIFEST `[!] bailed: crit_high_volume`; run `git grep -l "<component-basename>"` across other components; append "Potential dependents (text-grep — incomplete; validate manually for critical APIs)" to REPORT.md and MANIFEST.md; skip TASKS.md generation; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff.patch:255:8. Mark MANIFEST state `[a] audited`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff.patch:287:For each component with state `[a] audited` in MANIFEST order (synthetic `<slug>-cross-cutting` first):
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff.patch:290:2. If proceed: mark MANIFEST `[i] implementing`; invoke `/z-implement-all --tasks=z-harness/plans/<slug>-<component>/TASKS.md`; wait for completion; mark MANIFEST `[x] done`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff.patch:291:3. If skip: mark MANIFEST `[s] skipped: user`; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T001/diff.patch:294:On re-invoke with a component in `[i] implementing` state (interrupted mid-implement): AskUser — resume with `/z-implement-all` on this component / mark `[s] skipped` / mark `[x] done` (if completed manually) / abort.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/SUMMARY.md:7:V1 fixes accepted: --components=<file> executable code, MANIFEST_EXISTS gating, unclaimed dedup, cross-method de-dup dict, Poetry from+include, setup.cfg find: form, EXTRA_COMPONENTS init, telemetry stderr warning.
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:73:Check for an existing slug dir in the canonical plans directory (`z-harness/plans/`). If a MANIFEST.md is found there, this is a **resume** — skip decomposition phases and jump to the next non-terminal MANIFEST state. If only a slug collision without MANIFEST, prompt the user to confirm or choose a different slug.
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:221:- Is there a `MANIFEST.md` already present under `$Z_HARNESS_PLAN_DIR/`? If so, this is a resume — describe the current MANIFEST state to the user and confirm whether they want to resume or restart.
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:303:MANIFEST_FILES = ["Cargo.toml", "pyproject.toml", "setup.cfg", "package.json"]
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:424:MANIFEST_EXISTS = any(
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:425:    os.path.isfile(os.path.join(repo_root, mf)) for mf in MANIFEST_FILES
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:448:if not MANIFEST_EXISTS:
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:652:### Step 6 — Initialize MANIFEST.md
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:654:Write `$Z_HARNESS_PLAN_DIR/MANIFEST.md` with all confirmed components in `[ ] pending` state:
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:666:    f"# Uplift MANIFEST — {slug}",
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:679:with open(os.path.join(plan_dir, "MANIFEST.md"), "w") as f:
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:681:print("wrote MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:851:Instructions: Examine the source map files for cross-component issues. For each finding, emit an explicit \`component: <slug-from-MANIFEST>\` marker (use the exact slug from the components table, or \`component: global\` for issues spanning all components). Then classify each finding as one of:
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:1160:Insert `<slug>-cross-cutting` as the FIRST row in MANIFEST.md:
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:1163:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_SLUG" "$CROSS_DIR" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:1184:    print(f"updated existing {cross_slug} row in MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:1193:    print(f"inserted {cross_slug} as first row in MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:1222:For each component in MANIFEST `pending` state (processing synthetic `<slug>-cross-cutting` first if it exists):
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:1224:1. Mark MANIFEST state `[~] auditing` immediately before dispatch.
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:1225:2. Dispatch one `auditor` subagent per `--dimensions` value in parallel. Inject `rubric_path` (absolute path of `./STYLE.md`) for `cleanliness` and `design` dimensions when STYLE.md is present and `NO_STYLE` is not set. Inject `cross_cutting_context` from CROSS-CUTTING.md entries matching this component's MANIFEST slug (exact match).
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:1228:5. Auto-bail check: if `>10 CRIT-HIGH` OR `>30 total` findings → mark MANIFEST `[!] bailed: crit_high_volume`; run `git grep -l "<component-basename>"` across other components; append "Potential dependents (text-grep — incomplete; validate manually for critical APIs)" to REPORT.md and MANIFEST.md; skip TASKS.md generation; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:1231:8. Mark MANIFEST state `[a] audited`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:1263:For each component with state `[a] audited` in MANIFEST order (synthetic `<slug>-cross-cutting` first):
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:1266:2. If proceed: mark MANIFEST `[i] implementing`; invoke `/z-implement-all --tasks=z-harness/plans/<slug>-<component>/TASKS.md`; wait for completion; mark MANIFEST `[x] done`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:1267:3. If skip: mark MANIFEST `[s] skipped: user`; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch:1270:On re-invoke with a component in `[i] implementing` state (interrupted mid-implement): AskUser — resume with `/z-implement-all` on this component / mark `[s] skipped` / mark `[x] done` (if completed manually) / abort.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/current.md:40:Check for an existing slug dir in the canonical plans directory (`z-harness/plans/`). If a MANIFEST.md is found there, this is a **resume** — skip decomposition phases and jump to the next non-terminal MANIFEST state. If only a slug collision without MANIFEST, prompt the user to confirm or choose a different slug.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/current.md:188:- Is there a `MANIFEST.md` already present under `$Z_HARNESS_PLAN_DIR/`? If so, this is a resume — describe the current MANIFEST state to the user and confirm whether they want to resume or restart.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/current.md:448:### Step 6 — Initialize MANIFEST.md
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/current.md:450:Write `$Z_HARNESS_PLAN_DIR/MANIFEST.md` with all confirmed components in `[ ] pending` state:
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/current.md:462:    f"# Uplift MANIFEST — {slug}",
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/current.md:475:with open(os.path.join(plan_dir, "MANIFEST.md"), "w") as f:
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/current.md:477:print("wrote MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/current.md:508:If any `global-task` findings exist, create a synthetic component named `<slug>-cross-cutting` and insert it FIRST in MANIFEST.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/current.md:520:For each component in MANIFEST `pending` state (processing synthetic `<slug>-cross-cutting` first if it exists):
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/current.md:522:1. Mark MANIFEST state `[~] auditing` immediately before dispatch.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/current.md:523:2. Dispatch one `auditor` subagent per `--dimensions` value in parallel. Inject `rubric_path` (absolute path of `./STYLE.md`) for `cleanliness` and `design` dimensions when STYLE.md is present and `NO_STYLE` is not set. Inject `cross_cutting_context` from CROSS-CUTTING.md entries matching this component's MANIFEST slug (exact match).
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/current.md:526:5. Auto-bail check: if `>10 CRIT-HIGH` OR `>30 total` findings → mark MANIFEST `[!] bailed: crit_high_volume`; run `git grep -l "<component-basename>"` across other components; append "Potential dependents (text-grep — incomplete; validate manually for critical APIs)" to REPORT.md and MANIFEST.md; skip TASKS.md generation; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/current.md:529:8. Mark MANIFEST state `[a] audited`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/current.md:561:For each component with state `[a] audited` in MANIFEST order (synthetic `<slug>-cross-cutting` first):
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/current.md:564:2. If proceed: mark MANIFEST `[i] implementing`; invoke `/z-implement-all --tasks=z-harness/plans/<slug>-<component>/TASKS.md`; wait for completion; mark MANIFEST `[x] done`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/current.md:565:3. If skip: mark MANIFEST `[s] skipped: user`; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/current.md:568:On re-invoke with a component in `[i] implementing` state (interrupted mid-implement): AskUser — resume with `/z-implement-all` on this component / mark `[s] skipped` / mark `[x] done` (if completed manually) / abort.
z-harness/plans/tiered-quality-uplift/archive/tasks/T003/SUMMARY.md:7:V1 fixes accepted: skip control-flow guard, full merge heredoc, root-dir fallback, source-ext restriction, G_COUNT ordering, parser order-independence, MANIFEST idempotency, grep telemetry bug.
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:73:Check for an existing slug dir in the canonical plans directory (`z-harness/plans/`). If a MANIFEST.md is found there, this is a **resume** — skip decomposition phases and jump to the next non-terminal MANIFEST state. If only a slug collision without MANIFEST, prompt the user to confirm or choose a different slug.
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:221:- Is there a `MANIFEST.md` already present under `$Z_HARNESS_PLAN_DIR/`? If so, this is a resume — describe the current MANIFEST state to the user and confirm whether they want to resume or restart.
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:303:MANIFEST_FILES = ["Cargo.toml", "pyproject.toml", "setup.cfg", "package.json"]
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:424:MANIFEST_EXISTS = any(
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:425:    os.path.isfile(os.path.join(repo_root, mf)) for mf in MANIFEST_FILES
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:448:if not MANIFEST_EXISTS:
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:652:### Step 6 — Initialize MANIFEST.md
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:654:Write `$Z_HARNESS_PLAN_DIR/MANIFEST.md` with all confirmed components in `[ ] pending` state:
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:666:    f"# Uplift MANIFEST — {slug}",
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:679:with open(os.path.join(plan_dir, "MANIFEST.md"), "w") as f:
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:681:print("wrote MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:851:Instructions: Examine the source map files for cross-component issues. For each finding, emit an explicit \`component: <slug-from-MANIFEST>\` marker (use the exact slug from the components table, or \`component: global\` for issues spanning all components). Then classify each finding as one of:
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1160:Insert `<slug>-cross-cutting` as the FIRST row in MANIFEST.md:
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1163:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_SLUG" "$CROSS_DIR" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1184:    print(f"updated existing {cross_slug} row in MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1193:    print(f"inserted {cross_slug} as first row in MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1222:Iterate every component in MANIFEST with state `[ ] pending`, **excluding** any row whose slug ends in `-cross-cutting` or whose component column is `(global)` — the synthetic cross-cutting component inserted by Phase 2 (T003) is handled separately in Phase 5 and must not be re-audited here. For each qualifying component, run Steps 1–8 below.
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1240:### Step 1 — Read MANIFEST and collect pending components
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1242:Parse MANIFEST.md to collect rows with state `[ ] pending`. Process them in the order they appear (synthetic `<slug>-cross-cutting` is first if present).
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1245:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1288:Update the MANIFEST row immediately before any dispatch:
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1291:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1565:2. Compute `OTHER_COMP_PATHS` from MANIFEST (all Path-column values except the bailing component and the synthetic cross-cutting row), then run a text-grep to find references:
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1569:   # Derive OTHER_COMP_PATHS from MANIFEST: all Path-column values except COMP_PATH and cross-cutting synthetic rows
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1570:   OTHER_COMP_PATHS="$(python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_PATH" <<'INNEREOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1610:4. Append the dependents warning block to MANIFEST.md's `## Dependents warnings (post-bail)` section (create the section if absent):
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1613:   python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "$COMP_PATH" "$DEPS_FOUND" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1648:5. Mark MANIFEST row as `[!] bailed: crit_high_volume` and populate Audit findings + Bail reason columns:
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1651:   python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "crit_high_volume" \
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1753:Update the MANIFEST row's TASKS.md column to `<abs path to COMP_PLAN_DIR/TASKS.md>`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1755:#### Step 2j — Mark `[a] audited` and emit done event
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1758:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "$COMP_PLAN_DIR/TASKS.md" \
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1790:    cells[1] = " [a] audited "
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1814:cp "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-audits.md"
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1847:For each component with state `[a] audited` in MANIFEST order (synthetic `<slug>-cross-cutting` first):
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1850:2. If proceed: mark MANIFEST `[i] implementing`; invoke `/z-implement-all --tasks=z-harness/plans/<slug>-<component>/TASKS.md`; wait for completion; mark MANIFEST `[x] done`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1851:3. If skip: mark MANIFEST `[s] skipped: user`; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T004/diff.patch:1854:On re-invoke with a component in `[i] implementing` state (interrupted mid-implement): AskUser — resume with `/z-implement-all` on this component / mark `[s] skipped` / mark `[x] done` (if completed manually) / abort.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff-v1.patch:40:Check for an existing slug dir in the canonical plans directory (`z-harness/plans/`). If a MANIFEST.md is found there, this is a **resume** — skip decomposition phases and jump to the next non-terminal MANIFEST state. If only a slug collision without MANIFEST, prompt the user to confirm or choose a different slug.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff-v1.patch:188:- Is there a `MANIFEST.md` already present under `$Z_HARNESS_PLAN_DIR/`? If so, this is a resume — describe the current MANIFEST state to the user and confirm whether they want to resume or restart.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff-v1.patch:448:### Step 6 — Initialize MANIFEST.md
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff-v1.patch:450:Write `$Z_HARNESS_PLAN_DIR/MANIFEST.md` with all confirmed components in `[ ] pending` state:
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff-v1.patch:462:    f"# Uplift MANIFEST — {slug}",
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff-v1.patch:475:with open(os.path.join(plan_dir, "MANIFEST.md"), "w") as f:
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff-v1.patch:477:print("wrote MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff-v1.patch:508:If any `global-task` findings exist, create a synthetic component named `<slug>-cross-cutting` and insert it FIRST in MANIFEST.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff-v1.patch:520:For each component in MANIFEST `pending` state (processing synthetic `<slug>-cross-cutting` first if it exists):
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff-v1.patch:522:1. Mark MANIFEST state `[~] auditing` immediately before dispatch.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff-v1.patch:523:2. Dispatch one `auditor` subagent per `--dimensions` value in parallel. Inject `rubric_path` (absolute path of `./STYLE.md`) for `cleanliness` and `design` dimensions when STYLE.md is present and `NO_STYLE` is not set. Inject `cross_cutting_context` from CROSS-CUTTING.md entries matching this component's MANIFEST slug (exact match).
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff-v1.patch:526:5. Auto-bail check: if `>10 CRIT-HIGH` OR `>30 total` findings → mark MANIFEST `[!] bailed: crit_high_volume`; run `git grep -l "<component-basename>"` across other components; append "Potential dependents (text-grep — incomplete; validate manually for critical APIs)" to REPORT.md and MANIFEST.md; skip TASKS.md generation; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff-v1.patch:529:8. Mark MANIFEST state `[a] audited`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff-v1.patch:561:For each component with state `[a] audited` in MANIFEST order (synthetic `<slug>-cross-cutting` first):
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff-v1.patch:564:2. If proceed: mark MANIFEST `[i] implementing`; invoke `/z-implement-all --tasks=z-harness/plans/<slug>-<component>/TASKS.md`; wait for completion; mark MANIFEST `[x] done`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff-v1.patch:565:3. If skip: mark MANIFEST `[s] skipped: user`; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff-v1.patch:568:On re-invoke with a component in `[i] implementing` state (interrupted mid-implement): AskUser — resume with `/z-implement-all` on this component / mark `[s] skipped` / mark `[x] done` (if completed manually) / abort.
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:73:Check for an existing slug dir in the canonical plans directory (`z-harness/plans/`). If a MANIFEST.md is found there, this is a **resume** — skip decomposition phases and jump to the next non-terminal MANIFEST state. If only a slug collision without MANIFEST, prompt the user to confirm or choose a different slug.
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:221:- Is there a `MANIFEST.md` already present under `$Z_HARNESS_PLAN_DIR/`? If so, this is a resume — describe the current MANIFEST state to the user and confirm whether they want to resume or restart.
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:303:MANIFEST_FILES = ["Cargo.toml", "pyproject.toml", "setup.cfg", "package.json"]
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:424:MANIFEST_EXISTS = any(
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:425:    os.path.isfile(os.path.join(repo_root, mf)) for mf in MANIFEST_FILES
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:448:if not MANIFEST_EXISTS:
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:652:### Step 6 — Initialize MANIFEST.md
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:654:Write `$Z_HARNESS_PLAN_DIR/MANIFEST.md` with all confirmed components in `[ ] pending` state:
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:666:    f"# Uplift MANIFEST — {slug}",
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:679:with open(os.path.join(plan_dir, "MANIFEST.md"), "w") as f:
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:681:print("wrote MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:851:Instructions: Examine the source map files for cross-component issues. For each finding, emit an explicit \`component: <slug-from-MANIFEST>\` marker (use the exact slug from the components table, or \`component: global\` for issues spanning all components). Then classify each finding as one of:
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1160:Insert `<slug>-cross-cutting` as the FIRST row in MANIFEST.md:
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1163:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_SLUG" "$CROSS_DIR" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1184:    print(f"updated existing {cross_slug} row in MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1193:    print(f"inserted {cross_slug} as first row in MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1222:Iterate every component in MANIFEST with state `[ ] pending`, **excluding** any row whose slug ends in `-cross-cutting` or whose component column is `(global)` — the synthetic cross-cutting component inserted by Phase 2 (T003) is handled separately in Phase 5 and must not be re-audited here. For each qualifying component, run Steps 1–8 below.
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1240:### Step 1 — Read MANIFEST and collect pending components
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1242:Parse MANIFEST.md to collect rows with state `[ ] pending`. Process them in the order they appear (synthetic `<slug>-cross-cutting` is first if present).
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1245:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1288:Update the MANIFEST row immediately before any dispatch:
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1291:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1565:2. Compute `OTHER_COMP_PATHS` from MANIFEST (all Path-column values except the bailing component and the synthetic cross-cutting row), then run a text-grep to find references:
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1569:   # Derive OTHER_COMP_PATHS from MANIFEST: all Path-column values except COMP_PATH and cross-cutting synthetic rows
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1570:   OTHER_COMP_PATHS="$(python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_PATH" <<'INNEREOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1610:4. Append the dependents warning block to MANIFEST.md's `## Dependents warnings (post-bail)` section (create the section if absent):
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1613:   python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "$COMP_PATH" "$DEPS_FOUND" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1648:5. Mark MANIFEST row as `[!] bailed: crit_high_volume` and populate Audit findings + Bail reason columns:
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1651:   python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "crit_high_volume" \
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1753:Update the MANIFEST row's TASKS.md column to `<abs path to COMP_PLAN_DIR/TASKS.md>`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1755:#### Step 2j — Mark `[a] audited` and emit done event
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1758:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "$COMP_PLAN_DIR/TASKS.md" \
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1790:    cells[1] = " [a] audited "
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1814:cp "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-audits.md"
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1827:### Step 1 — Aggregate queue summary from MANIFEST
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1829:Parse MANIFEST.md to compute counts:
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1832:PHASE4_SUMMARY="$(python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$SLUG" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1859:    if '[a] audited' in state:
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1947:> - Dependents warnings: `<DEP_WARN_COUNT>` `<if > 0: note "see MANIFEST.md Dependents warnings section">`
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1954:cp "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase4-review-gate.md"
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1969:Parse MANIFEST.md to collect rows with state `[a] audited` **plus** any `[i] implementing` rows (interrupted on a prior invocation). Apply the ordering rule: the synthetic `<slug>-cross-cutting` row is always processed first, regardless of its physical position in the table.
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1972:IMPL_QUEUE="$(python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$SLUG" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:1997:    actionable = '[a] audited' in state or '[i] implementing' in state
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2006:        "implementing": '[i] implementing' in state,
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2025:#### Step 2a — Handle `[i] implementing` (interrupted resume)
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2027:If the row state is `[i] implementing` (set on a prior invocation that was interrupted before completion):
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2031:> Component `<component>` is in state `[i] implementing` — it was being implemented when the last invocation was interrupted.
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2035:> 2. Mark as done — the implementation was completed manually; update MANIFEST to `[x] done`
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2036:> 3. Skip — mark as `[s] skipped: user` and move on
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2044:- **Option 2 (Mark done):** run the manifest_write block from Step 2d with state `[x] done`, emit `component_implement_done` with `outcome: "marked_done_manually"`, continue to the next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2045:- **Option 3 (Skip):** run the manifest_write block from Step 2d with state `[s] skipped: user`, continue to the next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2048:#### Step 2b — AskUser gate (normal `[a] audited` components)
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2050:If the row state was `[a] audited` (not a resume from `[i] implementing`):
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2083:- **Skip:** run the manifest_write block in Step 2d with state `[s] skipped: user`; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2088:Emit `component_implement_start` event and mark MANIFEST `[i] implementing` BEFORE dispatch (so an interrupt is detectable on next resume):
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2094:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "[i] implementing" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2138:Then **exit** the current `/z-uplift` invocation cleanly (do not attempt to wait for `/z-implement-all` inline — it is a separate slash command that the user runs). The next `/z-uplift` invocation will detect the `[i] implementing` row and check completion via Step 2a above.
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2140:Note: "completion detection" on resume (Step 2a option 2) works as follows — the user can manually mark `[x] done` after `/z-implement-all` finishes, or they can re-invoke with option 1 (Resume) which re-presents the `/z-implement-all` command for any remaining pending tasks.
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2142:#### Step 2d — MANIFEST state update helper
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2147:python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$COMP_SLUG" "<new_state>" <<'PYEOF'
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2183:Valid `new_state` values used in Phase 5: `[i] implementing`, `[x] done`, `[s] skipped: user`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2189:1. Do NOT modify the current component's MANIFEST row (leave it in `[a] audited` or `[i] implementing`).
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2190:2. Do NOT modify any subsequent component's MANIFEST row.
z-harness/plans/tiered-quality-uplift/archive/tasks/T005/diff.patch:2217:cp "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase5-implement.md"
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/delta-v2.patch:115:+MANIFEST_FILES = ["Cargo.toml", "pyproject.toml", "setup.cfg", "package.json"]
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/delta-v2.patch:233:+MANIFEST_EXISTS = any(
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/delta-v2.patch:234:+    os.path.isfile(os.path.join(repo_root, mf)) for mf in MANIFEST_FILES
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/delta-v2.patch:247:+if not MANIFEST_EXISTS:
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/amendment.md:20:- L209 (gotchas: text-grep dependents): note "labeled as 'potential / incomplete' in REPORT.md and MANIFEST.md".
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/amendment.md:34:  - T006: add `[i] implementing` resume branch acceptance bullet; add backup-before-delete for `--refresh-component`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:73:Check for an existing slug dir in the canonical plans directory (`z-harness/plans/`). If a MANIFEST.md is found there, this is a **resume** — skip decomposition phases and jump to the next non-terminal MANIFEST state. If only a slug collision without MANIFEST, prompt the user to confirm or choose a different slug.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:221:- Is there a `MANIFEST.md` already present under `$Z_HARNESS_PLAN_DIR/`? If so, this is a resume — describe the current MANIFEST state to the user and confirm whether they want to resume or restart.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:303:MANIFEST_FILES = ["Cargo.toml", "pyproject.toml", "setup.cfg", "package.json"]
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:424:MANIFEST_EXISTS = any(
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:425:    os.path.isfile(os.path.join(repo_root, mf)) for mf in MANIFEST_FILES
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:448:if not MANIFEST_EXISTS:
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:652:### Step 6 — Initialize MANIFEST.md
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:654:Write `$Z_HARNESS_PLAN_DIR/MANIFEST.md` with all confirmed components in `[ ] pending` state:
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:666:    f"# Uplift MANIFEST — {slug}",
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:679:with open(os.path.join(plan_dir, "MANIFEST.md"), "w") as f:
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:681:print("wrote MANIFEST.md")
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:712:If any `global-task` findings exist, create a synthetic component named `<slug>-cross-cutting` and insert it FIRST in MANIFEST.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:724:For each component in MANIFEST `pending` state (processing synthetic `<slug>-cross-cutting` first if it exists):
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:726:1. Mark MANIFEST state `[~] auditing` immediately before dispatch.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:727:2. Dispatch one `auditor` subagent per `--dimensions` value in parallel. Inject `rubric_path` (absolute path of `./STYLE.md`) for `cleanliness` and `design` dimensions when STYLE.md is present and `NO_STYLE` is not set. Inject `cross_cutting_context` from CROSS-CUTTING.md entries matching this component's MANIFEST slug (exact match).
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:730:5. Auto-bail check: if `>10 CRIT-HIGH` OR `>30 total` findings → mark MANIFEST `[!] bailed: crit_high_volume`; run `git grep -l "<component-basename>"` across other components; append "Potential dependents (text-grep — incomplete; validate manually for critical APIs)" to REPORT.md and MANIFEST.md; skip TASKS.md generation; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:733:8. Mark MANIFEST state `[a] audited`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:765:For each component with state `[a] audited` in MANIFEST order (synthetic `<slug>-cross-cutting` first):
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:768:2. If proceed: mark MANIFEST `[i] implementing`; invoke `/z-implement-all --tasks=z-harness/plans/<slug>-<component>/TASKS.md`; wait for completion; mark MANIFEST `[x] done`.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:769:3. If skip: mark MANIFEST `[s] skipped: user`; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/tasks/T002/diff.patch:772:On re-invoke with a component in `[i] implementing` state (interrupted mid-implement): AskUser — resume with `/z-implement-all` on this component / mark `[s] skipped` / mark `[x] done` (if completed manually) / abort.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/TASKS.md:34:- If `global-task` count > 0: create `$Z_HARNESS_PLAN_DIR.replace(/<slug>$/, '<slug>-cross-cutting')/{SPEC.md,PLAN.md,TASKS.md}` (minimal SPEC pointing at CROSS-CUTTING.md; TASKS.md generated one-task-per-G-NNN with aggregated `**Files:**` lines); insert as the FIRST row in MANIFEST.md.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/TASKS.md:44:- For each component in MANIFEST `pending` state (excluding the synthetic `<slug>-cross-cutting` if it exists — that's audited differently, since it's hand-written):
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/TASKS.md:45:  - Mark MANIFEST state `[~] auditing`. Emit `component_audit_start`.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/TASKS.md:51:  - Count CRITICAL+HIGH and total findings. If `total > 30 OR crit_high > 10`: mark MANIFEST `[!] bailed: crit_high_volume`; write REPORT.md with "BAILED — exceeds /z-audit thresholds" header; run `git grep -l "<component basename>" -- <other component paths>` and append "Dependents (text-grep):" section to REPORT.md and a `Dependents warnings` section to MANIFEST.md; skip TASKS.md generation; emit `component_audit_done` with `bailed: true`; continue.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/TASKS.md:54:  - Mark MANIFEST state `[a] audited`. Emit `component_audit_done`.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/TASKS.md:63:- Phase 5: process synthetic `<uplift-slug>-cross-cutting` first (if present) THEN components in MANIFEST order with state `[a] audited`:
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/TASKS.md:65:  - On proceed: invoke `/z-implement-all --tasks=z-harness/plans/<uplift-slug>-<component-slug>/TASKS.md`. Wait for completion (this is the orchestrator's existing pause point — `/z-implement-all` may itself compaction-pause; resume on next `/z-uplift` invocation picks up the same component if not yet `[x] done`).
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/TASKS.md:66:  - Set MANIFEST `[i] implementing` before dispatch, `[x] done` on successful completion (detect by reading the dispatched TASKS.md and confirming all `[ ]` are `[x]`), `[s] skipped: user` on user-skip, leave-as-is on abort.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/TASKS.md:68:- On abort: log `run_end status: aborted_by_user`; exit cleanly. Re-invoke resumes at the same MANIFEST row.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/TASKS.md:71:- **Acceptance:** synthetic cross-cutting component is processed first (or skipped cleanly if absent); per-component AskUser gates work; MANIFEST state transitions are atomic per component; abort leaves remaining MANIFEST rows unchanged.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/TASKS.md:74:### [ ] T006 — MANIFEST.md schema + resume logic + --retry-bailed / --refresh-component flags
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/TASKS.md:75:- Implement MANIFEST.md emission at end of Phase 1 (initial state: all rows `[ ] pending`, synthetic `-cross-cutting` row prepended if Phase 2 added it).
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/TASKS.md:76:- Resume logic at Setup: parse existing MANIFEST.md (if present); identify next non-terminal state; jump to corresponding phase (audit if any `[ ] pending` or `[~] auditing` rows; implement if all are `[a] audited` or terminal). Emit `resume_detected` event.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/TASKS.md:79:- Atomic MANIFEST.md updates: read full file, mutate target row, write via tmpfile + `os.replace`.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/TASKS.md:82:- **Acceptance:** MANIFEST table updates row-by-row without corruption under simulated interrupts; resume detection works (delete a `[a] audited` row's TASKS.md and re-invoke → Phase 5 still picks it up; mark `[~] auditing` and re-invoke → Phase 3 redoes it); both flags mutate only the targeted rows.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/TASKS.md:98:- Create `docs/human/z-uplift.md`: 2-3 paragraphs covering what it does, when to use it vs `/z-audit` and `/z-mr-review`, the STYLE.md prerequisite, how to interpret MANIFEST states. Cite `commands/z-uplift.md:<line>` for the key phases.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/TASKS.md:131:  - Phase 5: AskUser per component fires; user picks "skip" to avoid actually modifying code in the smoke test; MANIFEST shows `[s] skipped: user` for scripts.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/TASKS.md:136:- **Acceptance:** all phases execute, all expected events appear in `archive/<RUN>/events.jsonl`, MANIFEST transitions correctly, no exceptions or unhandled error paths.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:34:- **Phase 2 — Cross-cutting pass** — dispatch `gemini-consultant` + `codex-consultant` in parallel on a curated source map AND STYLE.md (if present); merge findings into `CROSS-CUTTING.md` with three-tier classification (`global-task` / `per-component-context` / `risk`). Style-drift findings are explicitly called out (cite STYLE.md rule IDs). `global-task` items become a synthetic component named `<slug>-cross-cutting` inserted FIRST in MANIFEST.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:35:- **Phase 3 — Per-component audits** — for each component in MANIFEST order: dispatch `auditor` agents per dimension in parallel (mirroring `/z-audit` Phases 2–6 inline); inject STYLE.md as the authoritative rubric for `cleanliness` and `design` dimensions (if STYLE.md present); read CROSS-CUTTING.md `per-component-context` entries as additional input; produce per-component `REPORT.md` + `TASKS.md` in sibling plan dir `z-harness/plans/<slug>-<component>/`; inherit `/z-audit`'s >30-findings / >10-CRIT-HIGH auto-bail; on bail, run cheap text-grep across other components for the bailed component's symbols/paths and warn user. Update MANIFEST per-component state after each.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:37:- **Phase 5 — Sequential implement** — for each non-bailed component in MANIFEST order: AskUser gate (proceed / skip / abort); invoke `/z-implement-all --tasks=z-harness/plans/<slug>-<component>/TASKS.md`; update MANIFEST state to `[x] done` on success.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:54:├── MANIFEST.md                                      ← component table + state (resume authority)
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:116:If `global-task` count > 0 → synthetic component `<slug>-cross-cutting` inserted at top of MANIFEST. Its TASKS.md is hand-written from `global-task` entries (one task per G-NNN), with `**Files:**` lines aggregating affected paths.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:119:For each component in MANIFEST `pending` state:
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:120:1. Mark MANIFEST state `[~] auditing`.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:124:5. Auto-bail check: count CRITICAL+HIGH and total findings. If >10 CRIT-HIGH OR >30 total → mark MANIFEST `[!] bailed: crit_high_volume` (or `bailed: spec_problem` for STATUS: spec_problem from auditor); write partial REPORT.md; run cheap text-grep `git grep -l "<component-basename>"` across other components, append "Dependents (text-grep):" section to REPORT.md; skip TASKS.md generation; continue to next component.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:127:8. Mark MANIFEST state `[a] audited`.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:130:For each component with state `[a] audited`:
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:133:3. On completion: mark MANIFEST `[x] done`.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:134:4. On user-skip: mark MANIFEST `[s] skipped: user`.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:135:5. On abort: mark MANIFEST state for this and remaining components left unchanged; log `run_end status: aborted_by_user`; exit.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:139:### `commands/z-uplift.md` — MANIFEST.md shape
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:141:# Uplift MANIFEST — <slug>
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:149:| [x] done | <slug>-cross-cutting | (global) | 4 (2 HIGH) | — | z-harness/plans/<slug>-cross-cutting/TASKS.md |
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:150:| [a] audited | crates/foo | foo | 8 (1 HIGH) | — | z-harness/plans/<slug>-foo/TASKS.md |
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:158:States: `[ ] pending` `[~] auditing` `[a] audited` `[i] implementing` `[x] done` `[!] bailed: <reason>` `[s] skipped: <reason>`.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:160:Resume: on re-invoke, orchestrator parses MANIFEST, identifies next non-terminal state, resumes at the matching phase (audit or implement). `--retry-bailed` and `--refresh-component <name>` mutate states accordingly.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:202:- MANIFEST.md is the resume authority; no parallel state file.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:203:- Components processed sequentially in MANIFEST order; synthetic `-cross-cutting` first if it exists.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:223:- Idempotent: re-invoking `/z-uplift` with no flags resumes at the next non-terminal MANIFEST state.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:236:- All components bail → MANIFEST shows nothing in `[a] audited` state; Phase 5 has nothing to do; recommend user run `/z-plan` on the bailed components individually.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/SPEC.md:237:- User re-invokes mid-implement (Ctrl-C during Phase 5) → MANIFEST shows last component `[i] implementing`. Re-invoke detects this, asks user: resume with `/z-implement-all` on this component / mark `[s] skipped` / mark `[x] done` (if they finished manually) / abort.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/PLAN.md:13:- **D7 MANIFEST.md is the resume authority**; no parallel state file. `--retry-bailed` / `--refresh-component <name>` flags.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/PLAN.md:38:4. **Per-component audit loop** — Phase 3 implementation: per-component output dir scaffolding (`<uplift-slug>-<component-slug>/SPEC.md`, `PLAN.md`), parallel auditor dispatch with STYLE.md + cross-cutting context injection, bundled consultant critique on REPORT.md, auto-bail check, text-grep dependents reporting, TASKS.md promotion, codex-reviewer gate, MANIFEST state updates.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/PLAN.md:39:5. **Implement loop** — Phase 5 implementation: per-component AskUser gates, `/z-implement-all --tasks=` dispatch, MANIFEST state updates, abort handling. Process synthetic `<slug>-cross-cutting` first.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/PLAN.md:40:6. **MANIFEST + telemetry** — MANIFEST.md schema, state machine, resume logic for re-invokes, component-specific telemetry events, `--retry-bailed` / `--refresh-component` flag wiring.
z-harness/plans/tiered-quality-uplift/archive/20260526T030246Z-amend-tiered-quality-uplift/before/PLAN.md:43:9. **Smoke test** — run `/z-uplift --no-style --cross-cutting=skip --component scripts` against this repo as a single-component dry run; verify decomposition output, auditor dispatch, REPORT/TASKS generation, MANIFEST state machine.

exec
/bin/zsh -lc "nl -ba z-harness/plans/tiered-quality-uplift/TASKS.md | sed -n '62,73p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
    62	- **Note (T004 follow-up — 2 narrow majors in v2):** (a) Step 2j-bail replace_row callback mutates without checking cells[3] == comp_slug; symmetric audited path has the guard. (b) git grep dependents call with empty OTHER_COMP_PATHS searches whole repo (no path scope = unbounded match); guard with `if [ -n "$OTHER_COMP_PATHS" ]` else DEPS_FOUND="". Both fire only on rare codepaths; defer to follow-up.
    63	
    64	### [~] T005 — Implement Phase 4 (review gate) + Phase 5 (sequential implement loop)
    65	- Phase 4: aggregate queue summary to user (component count, total tasks, bailed components, dependents warnings). Push-notify + present plain summary, no AskUser (just informational, leads into Phase 5).
    66	- Phase 5: process synthetic `<uplift-slug>-cross-cutting` first (if present) THEN components in MANIFEST order with state `[a] audited`:
    67	  - AskUser per component: "Implement `<component>` (N tasks) now? proceed / skip / abort uplift".
    68	  - On proceed: invoke `/z-implement-all --tasks=z-harness/plans/<uplift-slug>-<component-slug>/TASKS.md`. Wait for completion (this is the orchestrator's existing pause point — `/z-implement-all` may itself compaction-pause; resume on next `/z-uplift` invocation picks up the same component if not yet `[x] done`).
    69	  - Set MANIFEST `[i] implementing` before dispatch, `[x] done` on successful completion (detect by reading the dispatched TASKS.md and confirming all `[ ]` are `[x]`), `[s] skipped: user` on user-skip, leave-as-is on abort.
    70	  - Emit `component_implement_start` / `component_implement_done` events.
    71	- On abort: log `run_end status: aborted_by_user`; exit cleanly. Re-invoke resumes at the same MANIFEST row.
    72	- **Files:** `commands/z-uplift.md` (modified)
    73	- **Depends on:** T004

exec
/bin/zsh -lc "nl -ba commands/z-uplift.md | sed -n '652,690p;1160,1198p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
   652	### Step 6 — Initialize MANIFEST.md
   653	
   654	Write `$Z_HARNESS_PLAN_DIR/MANIFEST.md` with all confirmed components in `[ ] pending` state:
   655	
   656	```bash
   657	python3 - "$Z_HARNESS_PLAN_DIR" "$COMPONENTS_JSON" "$SLUG" "$RUN" <<'PYEOF'
   658	import json, sys, os
   659	from datetime import datetime, timezone
   660	
   661	plan_dir, data_str, slug, run = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
   662	data = json.loads(data_str)
   663	components = data["components"]
   664	
   665	lines = [
   666	    f"# Uplift MANIFEST — {slug}",
   667	    "",
   668	    f"Generated: {datetime.now(timezone.utc).isoformat()}",
   669	    f"Run: {run}",
   670	    f"Detection: {'manual' if all(c['method']=='manual' for c in components) else 'auto' if all(c['method']!='manual' for c in components) else 'mixed'}",
   671	    "",
   672	    "| State | Component | Slug | Audit findings | Bail reason | TASKS.md |",
   673	    "|-------|-----------|------|----------------|-------------|----------|",
   674	]
   675	for c in components:
   676	    lines.append(f"| [ ] pending | {c['path']} | {c['slug']} | — | — | — |")
   677	lines.append("")
   678	
   679	with open(os.path.join(plan_dir, "MANIFEST.md"), "w") as f:
   680	    f.write("\n".join(lines) + "\n")
   681	print("wrote MANIFEST.md")
   682	PYEOF
   683	```
   684	
   685	### Step 7 — Phase 1 checkpoint
   686	
   687	Write checkpoint and log phase end:
   688	
   689	```bash
   690	cp "$Z_HARNESS_PLAN_DIR/COMPONENTS.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase1-decomposition.md"
  1160	Insert `<slug>-cross-cutting` as the FIRST row in MANIFEST.md:
  1161	
  1162	```bash
  1163	python3 - "$Z_HARNESS_PLAN_DIR/MANIFEST.md" "$Z_HARNESS_SLUG" "$CROSS_DIR" <<'PYEOF'
  1164	import sys, re
  1165	
  1166	manifest_path = sys.argv[1]
  1167	slug          = sys.argv[2]
  1168	cross_dir     = sys.argv[3]
  1169	
  1170	with open(manifest_path) as f:
  1171	    content = f.read()
  1172	
  1173	cross_slug = f"{slug}-cross-cutting"
  1174	new_row = f"| [ ] pending | {cross_slug} | (global) | — | — | {cross_dir}/TASKS.md |\n"
  1175	
  1176	# Idempotent: if a row for this cross-slug already exists, update it in place; else insert as first row.
  1177	existing_row_re = re.compile(
  1178	    rf'^\|[^|]*\|\s*{re.escape(cross_slug)}\s*\|[^\n]*\n',
  1179	    re.MULTILINE
  1180	)
  1181	if existing_row_re.search(content):
  1182	    # Update existing row (replace the whole row)
  1183	    content = existing_row_re.sub(new_row, content)
  1184	    print(f"updated existing {cross_slug} row in MANIFEST.md")
  1185	else:
  1186	    # Insert immediately after the header row separator line
  1187	    content = re.sub(
  1188	        r'(\|[-| ]+\|\n)',
  1189	        r'\1' + new_row,
  1190	        content,
  1191	        count=1
  1192	    )
  1193	    print(f"inserted {cross_slug} as first row in MANIFEST.md")
  1194	
  1195	with open(manifest_path, "w") as f:
  1196	    f.write(content)
  1197	PYEOF
  1198	```

exec
/bin/zsh -lc "nl -ba commands/z-uplift.md | sed -n '1698,1732p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
  1698	   ```bash
  1699	   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" component_audit_done \
  1700	     "$(printf '{"component":"%s","findings_total":%d,"findings_crit_high":%d,"bailed":true,"bail_reason":"crit_high_volume"}' \
  1701	        "$COMP_SLUG" "$TOTAL_COUNT" "$CRIT_HIGH_COUNT")"
  1702	   ```
  1703	
  1704	7. **Continue to next component** — do not generate TASKS.md or run the reviewer.
  1705	
  1706	#### Step 2h — Promote findings to TASKS.md (non-bail path)
  1707	
  1708	Only reached when bail condition is NOT met.
  1709	
  1710	Write `$COMP_PLAN_DIR/TASKS.md` in the exact format `/z-implement-all` consumes (mirror `/z-audit` Phase 5 shape):
  1711	
  1712	```markdown
  1713	# Audit TASKS — <component path>
  1714	
  1715	Status legend: `[ ]` pending · `[~]` in_progress · `[x]` done.
  1716	
  1717	### [ ] T001 — [SEVERITY] short subject
  1718	- One-paragraph context: why this matters, what evidence supports it (cite REPORT.md finding ID).
  1719	- **Files:** `<path>:<line>` (modified).
  1720	- **Depends on:** none | T00X.
  1721	- **Acceptance:** verifiable criteria.
  1722	- **Complexity:** low | medium | high
  1723	
  1724	### [ ] T002 — [SEVERITY] ...
  1725	```
  1726	
  1727	Severity prefix: `[CRITICAL] | [HIGH] | [MED] | [LOW]`. Group by phase (Phase A / B / ...) when tasks have ordering dependencies. Only actionable findings (those with a clear fix) go into TASKS.md; observations without a concrete recommendation stay in REPORT.md only.
  1728	
  1729	#### Step 2i — Dispatch reviewer over TASKS.md (mandatory safety gate)
  1730	
  1731	```
  1732	Agent(

codex
- **Blocker — `commands/z-uplift.md:2130-2140`**: Phase 5 does not invoke or wait for `/z-implement-all`; it marks the row `[i] implementing`, tells the user to run another command, exits, and never performs the required `[x] done` transition on completion. Fix by actually dispatching `/z-implement-all --tasks="$COMP_TASKS_MD"`, waiting/resuming at that pause point, validating the TASKS.md has no pending `[ ]` tasks, then marking `[x] done` and emitting `component_implement_done`.

- **Major — `commands/z-uplift.md:2140` and `commands/z-uplift.md:2203-2210`**: “Mark as done” is user-asserted and does not verify that the dispatched TASKS.md is complete, so MANIFEST can become `[x] done` while component tasks are still pending. Fix by reading `COMP_TASKS_MD` before any `[x] done` transition and refusing/continuing `[i] implementing` if pending task markers remain.

- **Major — `commands/z-uplift.md:2009-2011`**: Cross-cutting-first detection does not match the actual synthetic row emitted earlier, where `Component=<slug>-cross-cutting` and `Slug=(global)`, so the “regardless of physical position” ordering guarantee fails if the row is ever moved. Fix the predicate to recognize `comp == f"{slug}-cross-cutting"` or `row_slug == "(global)"`, and normalize the queue item’s implementation slug to `<slug>-cross-cutting`.

- **Major — `commands/z-uplift.md:1954`**: Phase 4 writes the summary checkpoint at `phase4-review-gate.md` and then immediately overwrites it with `MANIFEST.md`, destroying the review-gate artifact. Remove the copy or write it to a distinct archive filename such as `phase4-manifest.md`.

- **Major — `commands/z-uplift.md:2120-2126` and `commands/z-uplift.md:2173-2179`**: The MANIFEST update helper silently succeeds when it updates zero rows, and it would also update every duplicate matching slug, so state transitions are not reliably “atomic per component” in the correctness sense. Track replacement count, require exactly one matched row, write via temp file only on success, and fail loudly otherwise.
tokens used
49,915
- **Blocker — `commands/z-uplift.md:2130-2140`**: Phase 5 does not invoke or wait for `/z-implement-all`; it marks the row `[i] implementing`, tells the user to run another command, exits, and never performs the required `[x] done` transition on completion. Fix by actually dispatching `/z-implement-all --tasks="$COMP_TASKS_MD"`, waiting/resuming at that pause point, validating the TASKS.md has no pending `[ ]` tasks, then marking `[x] done` and emitting `component_implement_done`.

- **Major — `commands/z-uplift.md:2140` and `commands/z-uplift.md:2203-2210`**: “Mark as done” is user-asserted and does not verify that the dispatched TASKS.md is complete, so MANIFEST can become `[x] done` while component tasks are still pending. Fix by reading `COMP_TASKS_MD` before any `[x] done` transition and refusing/continuing `[i] implementing` if pending task markers remain.

- **Major — `commands/z-uplift.md:2009-2011`**: Cross-cutting-first detection does not match the actual synthetic row emitted earlier, where `Component=<slug>-cross-cutting` and `Slug=(global)`, so the “regardless of physical position” ordering guarantee fails if the row is ever moved. Fix the predicate to recognize `comp == f"{slug}-cross-cutting"` or `row_slug == "(global)"`, and normalize the queue item’s implementation slug to `<slug>-cross-cutting`.

- **Major — `commands/z-uplift.md:1954`**: Phase 4 writes the summary checkpoint at `phase4-review-gate.md` and then immediately overwrites it with `MANIFEST.md`, destroying the review-gate artifact. Remove the copy or write it to a distinct archive filename such as `phase4-manifest.md`.

- **Major — `commands/z-uplift.md:2120-2126` and `commands/z-uplift.md:2173-2179`**: The MANIFEST update helper silently succeeds when it updates zero rows, and it would also update every duplicate matching slug, so state transitions are not reliably “atomic per component” in the correctness sense. Track replacement count, require exactly one matched row, write via temp file only on success, and fail loudly otherwise.
