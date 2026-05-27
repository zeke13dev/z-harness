2026-05-27T03:33:30.135836Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-27T03:33:30.136376Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-27T03:33:30.136381Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-27T03:33:30.136384Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-suggest-memory/SKILL.md: invalid YAML: did not find expected key at line 3 column 35, while parsing a block mapping
2026-05-27T03:33:30.136385Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-27T03:33:30.136387Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-27T03:33:30.136388Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.133.0
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR]
reasoning effort: medium
reasoning summaries: none
session id: 019e677e-9739-7132-aa0c-5930db079032
--------
user
You are reviewing code that Claude just wrote for task z-debug-bisect-isolation (RETRY 1): Add Phase 2.5 bisect fast-path to /z-debug + new bisect-isolator Haiku agent.

This is the second review cycle — the prior cycle found 5 issues (2 blockers, 3 majors), all claimed fixed. Re-review focus: (1) Did the fixes land correctly? (2) Any NEW blockers/majors? (3) Confirm or push back on MAJOR 2 (telemetry ${#PROMPT}/${#RESPONSE} undefined — deferred as project-wide pattern).

Spec (excerpt):

The task adds a new Phase 2.5 — Regression bisect (conditional fast-path) to /z-debug:
1. Gate on three preconditions: Started ≠ unknown, Reproducibility confirmed: yes, repro is scriptable.
2. Dispatch a Haiku subagent (bisect-isolator) that: verifies refs exist, sanity-checks repro, runs `git bisect run`, captures offending SHA + diff, always runs `git bisect reset` even on failure.
3. On `STATUS: ok`: append EVID-NNN to Evidence Inventory (source: bisect), seed Phase 3a with bisect result block.
4. On `STATUS: bisect_unusable/refused/failed`: skip silently, proceed to Phase 3a.
5. Bisect never blocks the pipeline, never replaces hypothesis tournament, never pre-fills winning hypothesis.

Acceptance criteria (from FIX.md):
- agents/bisect-isolator.md exists with: YAML frontmatter (name: bisect-isolator, tools: Bash/Read/Grep/Glob, model: haiku); explicit input contract; refusal-check section listing destructive-verb grep + interpretive_work refusal; STATUS return shape with `ok | bisect_unusable | refused | failed`; telemetry start/end using scripts/log-phase.sh.
- commands/z-debug.md Phase 2.5 section exists between Phase 2 and Phase 3a with: gate preconditions, dispatch shape, behavior on ok/bisect_unusable/refused, reference to new agent.
- Phase-visibility matrix gains row for Phase 2.5 (consultant call: N/A — Haiku not a consultant).
- Hard rules updated to note bisect is fast-path-only.
- Codex review passes (Phase 8).

Prior review findings (all claimed fixed):
1. BLOCKER 1: Archive path mismatch `$BASE/archive/tasks/<task-id>/` vs `$Z_HARNESS_PLAN_DIR/archive/<run-id>/` — FIXED via global replace to `$BASE/archive/<task-id>/`, matching artifact path in commands/z-debug.md also updated.
2. BLOCKER 2: No trap for git bisect reset — FIXED: added explicit `trap cleanup_bisect EXIT` in new step 2.5 of bisect-isolator.md immediately after pre-flight, with idempotent reset.
3. MAJOR 1: Refusal-check verb-grep underspecified — FIXED: concrete extended-regex `DESTRUCTIVE_RE` with grep -iE invocation now in step 2.
4. MAJOR 2: Telemetry ${#PROMPT}/${#RESPONSE} undefined — INTENTIONALLY NOT CHANGED: matches existing agents/remote-runner.md:93-94 convention; treating as project-wide pattern.
5. MAJOR 3: Missing mkdir -p for tee target — FIXED: added `mkdir -p "$BASE/archive/<task-id>"` before bisect start in step 5.

Diff (primary artifact — focus scrutiny on what changed):

```diff
diff --git a/commands/z-debug.md b/commands/z-debug.md
index 018a540..cb3362b 100644
--- a/commands/z-debug.md
+++ b/commands/z-debug.md
@@ -137,6 +137,69 @@ Append `## Evidence Inventory` to `DEBUG.md`:
 
 Default recommendation: gather more evidence. Debug-on-inference often fixes the wrong thing.
 
+## Phase 2.5 — Regression bisect (conditional fast-path)
+
+When the bug is a regression with a known-good baseline and a scriptable repro, `git bisect run` deterministically locates the offending commit + line-level diff without any LLM reasoning. This phase is a **fast-path evidence augmentation** — it never replaces the hypothesis tournament, only seeds it.
+
+### Gate (all three must hold)
+
+1. **`Started:` field from Phase 1 is not "unknown"** — user supplied a last-good ref / SHA / tag / branch.
+2. **`Reproducibility confirmed: yes`** in Phase 2's Evidence Inventory — not partial, not no.
+3. **Repro is scriptable** — the orchestrator can produce a single shell command that exits 0 when the bug is absent (good) and non-zero when present (bad). If repro requires interactive input, multiple manual steps, or a long-running service, the repro is not scriptable — skip Phase 2.5.
+
+If any gate fails → skip Phase 2.5 silently and proceed to Phase 3a unchanged. Do not push-notify the skip.
+
+### Dispatch shape
+
+```
+Agent(
+  subagent_type="bisect-isolator",
+  description="Bisect regression for <slug>",
+  prompt="repro_command: <shell command, exit 0=good, non-zero=bad>\ngood_ref: <last-good SHA/tag/branch from Phase 1 Started field>\nbad_ref: HEAD\nrepo_root: <abs path>\ntask_id: <RUN>\n$BASE: $Z_HARNESS_PLAN_DIR"
+)
+```
+
+The orchestrator constructs `repro_command` from Phase 2's repro steps. If Phase 2 captured the repro as a failing test, `repro_command` is typically `cargo test -p <crate> <test_name>` or `python -m pytest <path>::<test>`; if Phase 2 captured it as a CLI invocation, use that verbatim. The repro must be self-contained — bisect will run it ~log₂(N) times across the range.
+
+### Handling the return
+
+Parse the `STATUS:` line:
+
+- **`STATUS: ok`** — bisect found the offending commit. Append a high-confidence evidence entry to the Evidence Inventory:
+
+  ```markdown
+  - **EVID-NNN:** (source: bisect) Offending commit `<offending_sha>` introduced the regression between `<good_ref>` and `<bad_ref>`. Files changed: `<list>`. Diff excerpt:
+    ```diff
+    <capped diff from bisect return>
+    ```
+  ```
+
+  The `(source: bisect)` tag marks this entry as deterministically derived rather than observationally captured. Subsequent phases treat it the same as any other `EVID-NNN`.
+
+  Then **seed Phase 3a's hypothesis-generation prompts** with the bisect result. Append a `Bisect result (high confidence):` block to the Round 1 prompt (immediately after Evidence Inventory) containing the offending SHA + diff excerpt. This shifts LLM attention from "where is the bug?" to "why did this specific change break things?" — which is the harder question bisect cannot answer mechanically.
+
+- **`STATUS: bisect_unusable`** — repro didn't invert across the range, refs not found, or bisect was inconclusive. Append a one-line note to DEBUG.md Evidence Inventory:
+
+  ```markdown
+  _Phase 2.5 bisect skipped: <reason from STATUS return>._
+  ```
+
+  Proceed to Phase 3a unchanged. Bisect's unusability is informative — `repro_passes_on_bad_ref` may indicate the bug is intermittent (Phase 2's "Reproducibility confirmed" was overclaimed); `repro_fails_on_good_ref` may indicate this is not actually a regression (the "good" baseline already had the bug). Mention this hint in the Phase 3a prompt as context, but do not derive hypotheses from it.
+
+- **`STATUS: refused`** — caller-side bug (destructive repro script, dirty working tree, interpretive_work request). Halt and ask the user via `AskUserQuestion` how to proceed:
+  - "Rewrite repro to avoid the refused condition" — return to Phase 2 to revise.
+  - "Skip bisect, proceed to Phase 3a" — record the refusal in DEBUG.md and continue.
+  - "Abandon" — log `debug_run_end {status: "abandoned"}` and stop.
+
+- **`STATUS: failed`** — bisect ran but couldn't converge (typically too many `skip` returns). Treat as `bisect_unusable` for routing purposes; the bisect log path is in the return for caller inspection.
+
+### Hard limits
+
+- **Bisect never blocks the pipeline.** All non-`ok` returns fall through to Phase 3a. The phase is a fast-path, not a gate.
+- **Bisect never replaces hypothesis generation.** Even on `STATUS: ok` with a single-line diff in the offending commit, Phase 3a–6 still runs. Bisect tells you WHAT changed; hypothesis tournament tells you WHY it broke things. A refactor commit can expose a latent bug elsewhere; Round 1+2 adversarial rounds are still valuable for surfacing this.
+- **Bisect's offending SHA does NOT pre-fill the winning hypothesis.** The Phase 6 fix-gate still requires `posterior == very_high` AND zero `unexplained` rows in the Evidence coverage table. The bisect evidence is one input among many.
+- **Honor the orchestrator-only likelihood-bucket rule.** The bisect-isolator return is raw mechanical output, not a likelihood assignment. The orchestrator (and only the orchestrator) decides how the bisect result weights subsequent likelihood judgments.
+
 ## Phase 3a — Round 1 hypothesis generation (3 LLMs, parallel, independent)
 
 **Contamination mitigation:** the orchestrator (Claude main thread) writes its OWN hypothesis block to a checkpoint file BEFORE dispatching the consultants. This prevents the orchestrator from re-reading consultant output and laundering it as "its own" hypothesis at merge time.
@@ -558,6 +621,7 @@ Push-notify: "Post-mortem ready: `$Z_HARNESS_PLAN_DIR/DEBUG.md` Post-mortem sect
   ```
 - `$Z_HARNESS_PLAN_DIR/archive/<run-id>/round1-orchestrator.md` — pre-dispatch checkpoint of the orchestrator's independent Round 1 hypotheses (contamination mitigation).
 - `$Z_HARNESS_PLAN_DIR/archive/<run-id>/transcripts/` — consultant transcripts.
+- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/bisect.log` + `offending-show.txt` + `offending-diff.patch` — Phase 2.5 bisect artifacts (only if Phase 2.5 ran and returned `ok`).
 - `$Z_HARNESS_PLAN_DIR/archive/<run-id>/diff.patch` — fix diff.
 - `$Z_HARNESS_PLAN_DIR/MR-REVIEW.md` — optional, if user opted into MR-style review in Phase 9.
 
@@ -567,7 +631,8 @@ Source of truth for what each subagent dispatch sees. Subagent prompts must neve
 
 | Phase | Consultant call | Sections passed | Forbidden | Raw test output? |
 |---|---|---|---|---|
-| 3a (Round 1) | both, MODE `generate-hypotheses-round1` | Problem; Evidence Inventory; doc-fetcher synthesis | Hypothesis Pool (doesn't exist yet); any orchestrator-internal block | No |
+| 2.5 (bisect) | bisect-isolator (Haiku, not a consultant) | repro_command, good_ref, bad_ref, repo_root, task_id | likelihood buckets, posteriors, any hypothesis content | N/A — mechanical only |
+| 3a (Round 1) | both, MODE `generate-hypotheses-round1` | Problem; Evidence Inventory (incl. bisect EVID if Phase 2.5 produced one); doc-fetcher synthesis; bisect result block if Phase 2.5 returned `ok` | Hypothesis Pool (doesn't exist yet); any orchestrator-internal block; likelihood buckets | No |
 | 3b (Round 2) | both, MODE `generate-hypotheses-round2-adversarial` | Problem; Evidence Inventory; Hypothesis Pool (full) | Test Matrix; Experiment Log; Score Updates | No |
 | 6 (optional Round 3) | both, MODE `generate-hypotheses-round1` | Problem; Evidence Inventory; eliminated `claim` text + falsifying `discriminating_test` only | priors, likelihoods, posteriors, full Eliminated Alternatives section | No |
 | 7 (fix consult) | both, MODE `light-fix` | Problem; Evidence Inventory; winning Hypothesis Pool rows; Experiment Log; draft Root Cause; draft Evidence coverage table | Eliminated Alternatives; Score Updates history | No |
@@ -585,4 +650,5 @@ Orchestrator alone reads raw test output and assigns likelihood buckets (Phase 6
 - **Wrong-tool gate (Phase 0) is non-skippable.** If the user already has a hypothesis, exit with a `/z-fix` recommendation — do not proceed.
 - **Never proceed past auto-bail thresholds** without explicit user override.
 - **Fix-gate is objective and binary.** Opens only when (a) winning hypothesis posterior == `very_high` AND (b) every `EVID-NNN` in the Evidence coverage table has status ∈ `{explained, falsifies_alternative, orthogonal_with_reason}` (zero `unexplained`).
+- **Phase 2.5 bisect is fast-path-only.** Bisect never blocks the pipeline, never replaces the hypothesis tournament, and never pre-fills the winning hypothesis. It augments the Evidence Inventory and seeds Phase 3a; the fix-gate still requires full posterior + evidence-coverage convergence.
 - **No emojis** anywhere in artifacts.
```

Surrounding context from bisect-isolator.md (NEW FILE):

=== agents/bisect-isolator.md (lines 58-72: Trap section) ===
```
### 2.5. Trap to guarantee `git bisect reset`

Install a shell trap IMMEDIATELY after the pre-flight check (step 3) so that ANY early exit — refusal-after-bisect-start, error, signal — still cleans up:

```bash
cleanup_bisect() {
  local rc=$?
  cd "<repo_root>" 2>/dev/null && git bisect reset >/dev/null 2>&1 || true
  return $rc
}
trap cleanup_bisect EXIT
```

The trap is idempotent — running `git bisect reset` outside a bisect is a no-op. Never leave a repo in mid-bisect state.
```

=== agents/bisect-isolator.md (lines 42-56: Refusal checks with DESTRUCTIVE_RE) ===
```
### 2. Refusal checks

Apply the verb-grep to `repro_command` BEFORE touching the repo. Concrete pattern (extended regex, case-insensitive — adapt the home-dir paths to your env):

```bash
DESTRUCTIVE_RE='rm[[:space:]]+-rf[[:space:]]+(/|~|\$HOME)|git[[:space:]]+push|git[[:space:]]+reset[[:space:]]+--hard[[:space:]]+[^H]|git[[:space:]]+branch[[:space:]]+-D|git[[:space:]]+filter-branch|curl[[:space:]]+-X[[:space:]]*(POST|PUT|DELETE|PATCH)|qtctl[[:space:]]+up[[:space:]]+(?!.*paper)|duckdb(?!.*-readonly).*\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\b|psql.*-c.*\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE)\b|>>?[[:space:]]*~/dev/qt-bot/(state|data|logs)|tee[[:space:]]+~/dev/qt-bot/(state|data|logs)|sed[[:space:]]+-i.*~/dev/qt-bot/(state|data|logs)'

if echo "<repro_command>" | grep -iE "$DESTRUCTIVE_RE" >/dev/null 2>&1; then
  MATCHED="$(echo "<repro_command>" | grep -ioE "$DESTRUCTIVE_RE" | head -1)"
  # Return STATUS: refused, reason: destructive_repro — found '$MATCHED'
  exit 0
fi
```
```

=== agents/bisect-isolator.md (lines 113-124: mkdir -p before bisect start) ===
```
### 5. Run `git bisect run`

```bash
cd "<repo_root>"
mkdir -p "$BASE/archive/<task-id>"
git bisect start
git bisect bad "<bad_ref>"
git bisect good "<good_ref>"

# git bisect run treats exit 0 = good, 1-124/126-127 = bad, 125 = skip.
# Repro script's natural 0/non-zero contract maps directly.
git bisect run bash -c "<repro_command>" 2>&1 | tee "$BASE/archive/<task-id>/bisect.log"
BISECT_EXIT=${PIPESTATUS[0]}
```
```

Scrutinize this code rigorously. Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, and a suggested fix.

IMPORTANT: Output budget — respect strictly:
- Total response under 8000 characters.
- Report blockers and majors only. Skip minors/nits unless a "minor" hides a correctness bug.
- One finding per bullet. Two sentences max per finding.
- No re-stating of code already in the diff. No summaries of what the code does. No restating the spec.

If there are no blockers or majors, respond with: No blockers or majors found. [optional 1-line note]
codex
I’ll verify the claimed fixes against the actual files, then focus the review on remaining blockers/majors rather than rehashing the diff.
exec
/bin/zsh -lc "sed -n '1,180p' agents/bisect-isolator.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
---
name: bisect-isolator
description: Haiku subagent that drives `git bisect run` between a known-good ref and HEAD using a caller-supplied repro script, then returns the offending commit SHA + line-level diff. Mechanical only — no interpretation of WHY the change broke things. Triggered by /z-debug Phase 2.5 when the bug is a regression with a known-good baseline and the repro is scriptable.
tools: Bash, Read, Grep, Glob
model: haiku
---

You are a fast, mechanical bisect-runner. The caller (typically `/z-debug` Phase 2.5) has a regression with a known-good ref and a scriptable repro. Your job: run `git bisect`, capture the offending commit + diff, return them. You do NOT reason about WHY the commit broke things — that's the caller's job (Sonnet/Opus).

## Inputs from caller

- `repro_command` — shell command that exits 0 when the bug is absent (good) and non-zero when present (bad). Must be self-contained and runnable from `repo_root`.
- `good_ref` — known-good commit SHA / tag / branch name. Must exist in the repo.
- `bad_ref` — known-bad commit SHA / tag / branch name. Default: `HEAD`.
- `repo_root` — absolute path to the git repo root (so you `cd` there before bisecting).
- `$BASE path` (e.g. `$Z_HARNESS_PLAN_DIR`) — for writing the bisect log archive.
- `task_id` — opaque identifier (typically the run id) for telemetry.

If any required input is missing, return `STATUS: refused`, reason `bad_input — <which field>`.

## What you DO NOT do

- **NO destructive repro scripts.** Before executing, grep `repro_command` for destructive verbs (case-insensitive):
  - `rm -rf` referencing any path OUTSIDE `<repo_root>/tmp/` or `<repo_root>/target/` or `/tmp/`
  - `git push`, `git reset --hard <non-HEAD-ref>`, `git branch -D`, `git filter-branch`
  - Writes under `~/dev/qt-bot/state/` or `~/dev/qt-bot/data/` or `~/dev/qt-bot/logs/` (`>>`, `>`, `tee`, `sed -i`, `cp ... ~/dev/qt-bot/state`)
  - Network mutations: `curl -X POST|PUT|DELETE|PATCH`, `qtctl up <manifest>` where `<manifest>` lacks `paper`, any `psql -c` / `duckdb` without `-readonly` containing write verbs (`INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE`)
  Any hit → refuse with `STATUS: refused`, reason `destructive_repro — <which verb>`.
- **NO interpretive reasoning.** If the caller asks "why did this commit break it" or "what's the root cause" — refuse with `STATUS: refused`, reason `interpretive_work — bounce to Sonnet/Opus`. Run bisect, return SHA + diff, stop.
- **NO bisect outside `repo_root`.** All `git bisect` invocations must `cd <repo_root>` first. Never operate on a different repo.
- **NO writing to the user's working tree.** Bisect mutates HEAD; on completion (success OR failure OR refusal AFTER `git bisect start`) you MUST run `git bisect reset` to restore the original HEAD. Treat this as a finally-block.

## Procedure

### 1. Telemetry: start event

```bash
TOKEN="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" start "tasks/<task-id>" bisect_isolate \
  "$(printf '{"id":"%s","good":"%s","bad":"%s","repro":"%s"}' "<task-id>" "<good-ref>" "<bad-ref>" "<repro-command>")")"
```

### 2. Refusal checks

Apply the verb-grep to `repro_command` BEFORE touching the repo. Concrete pattern (extended regex, case-insensitive — adapt the home-dir paths to your env):

```bash
DESTRUCTIVE_RE='rm[[:space:]]+-rf[[:space:]]+(/|~|\$HOME)|git[[:space:]]+push|git[[:space:]]+reset[[:space:]]+--hard[[:space:]]+[^H]|git[[:space:]]+branch[[:space:]]+-D|git[[:space:]]+filter-branch|curl[[:space:]]+-X[[:space:]]*(POST|PUT|DELETE|PATCH)|qtctl[[:space:]]+up[[:space:]]+(?!.*paper)|duckdb(?!.*-readonly).*\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\b|psql.*-c.*\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE)\b|>>?[[:space:]]*~/dev/qt-bot/(state|data|logs)|tee[[:space:]]+~/dev/qt-bot/(state|data|logs)|sed[[:space:]]+-i.*~/dev/qt-bot/(state|data|logs)'

if echo "<repro_command>" | grep -iE "$DESTRUCTIVE_RE" >/dev/null 2>&1; then
  MATCHED="$(echo "<repro_command>" | grep -ioE "$DESTRUCTIVE_RE" | head -1)"
  # Return STATUS: refused, reason: destructive_repro — found '$MATCHED'
  exit 0
fi
```

Adjust the `rm -rf` clause if the caller documented `<repo_root>/tmp/` or `<repo_root>/target/` as safe scratch — those paths are exempt by the spec but require an additional `grep -v` whitelist before the destructive grep.

### 2.5. Trap to guarantee `git bisect reset`

Install a shell trap IMMEDIATELY after the pre-flight check (step 3) so that ANY early exit — refusal-after-bisect-start, error, signal — still cleans up:

```bash
cleanup_bisect() {
  local rc=$?
  cd "<repo_root>" 2>/dev/null && git bisect reset >/dev/null 2>&1 || true
  return $rc
}
trap cleanup_bisect EXIT
```

The trap is idempotent — running `git bisect reset` outside a bisect is a no-op. Never leave a repo in mid-bisect state.

### 3. Pre-flight: refs exist + repo is clean

```bash
cd "<repo_root>"
git rev-parse --verify "<good_ref>^{commit}" >/dev/null 2>&1 || exit 11   # 11 = good_ref missing
git rev-parse --verify "<bad_ref>^{commit}"  >/dev/null 2>&1 || exit 12   # 12 = bad_ref missing
git diff --quiet && git diff --cached --quiet || exit 13                  # 13 = working tree dirty
```

If exit 11 → `STATUS: bisect_unusable`, reason `good_ref_not_found`.
If exit 12 → `STATUS: bisect_unusable`, reason `bad_ref_not_found`.
If exit 13 → `STATUS: refused`, reason `dirty_working_tree — caller must stash/commit before bisect`.

Capture the original HEAD for restoration: `ORIG_HEAD=$(git rev-parse HEAD)`.

### 4. Sanity-check the repro inverts across the range

This is the non-negotiable sanity gate. If the repro doesn't invert, bisect's answer is garbage.

```bash
# Repro on bad_ref must FAIL (non-zero exit)
git checkout --detach "<bad_ref>" >/dev/null 2>&1
bash -c "<repro_command>" > /tmp/bisect-sanity-bad.log 2>&1
BAD_EXIT=$?

# Repro on good_ref must PASS (zero exit)
git checkout --detach "<good_ref>" >/dev/null 2>&1
bash -c "<repro_command>" > /tmp/bisect-sanity-good.log 2>&1
GOOD_EXIT=$?

# Restore
git checkout --detach "$ORIG_HEAD" >/dev/null 2>&1
```

- If `BAD_EXIT == 0` (repro passes on the bad ref) → `STATUS: bisect_unusable`, reason `repro_passes_on_bad_ref — repro does not reproduce the bug at the reported bad commit`.
- If `GOOD_EXIT != 0` (repro fails on the good ref) → `STATUS: bisect_unusable`, reason `repro_fails_on_good_ref — the bug was present at the supposed good ref, so this is not a regression with this baseline`.
- Both correct → proceed.

### 5. Run `git bisect run`

```bash
cd "<repo_root>"
mkdir -p "$BASE/archive/<task-id>"
git bisect start
git bisect bad "<bad_ref>"
git bisect good "<good_ref>"

# git bisect run treats exit 0 = good, 1-124/126-127 = bad, 125 = skip.
# Repro script's natural 0/non-zero contract maps directly.
git bisect run bash -c "<repro_command>" 2>&1 | tee "$BASE/archive/<task-id>/bisect.log"
BISECT_EXIT=${PIPESTATUS[0]}
```

Parse the offending SHA from `bisect.log`. `git bisect run` prints a line of the form:
```
<sha> is the first bad commit
```

If no "first bad commit" line found → `STATUS: failed`, reason `bisect_inconclusive — see bisect.log`. (Most common cause: too many `git bisect skip` returns from exit 125 in the repro script.)

### 6. Capture diff for the offending commit

```bash
git show --stat --format=fuller "<offending_sha>" > "$BASE/archive/<task-id>/offending-show.txt"
git show "<offending_sha>" > "$BASE/archive/<task-id>/offending-diff.patch"

# For the inline return: capped diff
head -c 4096 "$BASE/archive/<task-id>/offending-diff.patch" > /tmp/bisect-diff-capped.txt
```

`FILES_CHANGED` is parsed from `--stat`:
```bash
git show --stat --format="" "<offending_sha>" | awk 'NF && $1 != "|" {print $1}' | head -50
```

### 7. Restore the repo (finally-block — always run)

```bash
git bisect reset >/dev/null 2>&1
# Verify HEAD restored
NEW_HEAD=$(git rev-parse HEAD)
if [ "$NEW_HEAD" != "$ORIG_HEAD" ]; then
  git checkout "$ORIG_HEAD" >/dev/null 2>&1
fi
```

If `git bisect reset` fails for any reason, surface it in the return SUMMARY — the caller may have a dirty repo to clean up manually.

### 8. Telemetry: end event

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" end "$TOKEN" \
  "$(printf '{"id":"%s","status":"%s","offending_sha":"%s","files_changed":%d,"subagent_model":"haiku","prompt_chars":%d,"response_chars":%d}' \
     "<task-id>" "$STATUS" "$OFFENDING_SHA" "$N_FILES" "${#PROMPT}" "${#RESPONSE}")"
```

## Return shape (required)

```
STATUS: ok | bisect_unusable | refused | failed
TASK: <task-id>
OFFENDING_SHA: <40-char SHA, or empty if STATUS != ok>
FILES_CHANGED:
  - <path>
  - <path>
  - ... (capped at 50 lines)
SUMMARY:
  <one paragraph: what bisect found, OR why it was unusable/refused/failed>

exec
/bin/zsh -lc "sed -n '120,180p' commands/z-debug.md && sed -n '610,660p' commands/z-debug.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:

### Reproducibility confirmed
<yes | no | partial; if no, explain>

### Inventory
- **EVID-001:** <text or quoted log line / fixture / metric>
- **EVID-002:** <text>
- **EVID-003:** <text>
- ...
```

**Each evidence entry gets a stable `EVID-NNN` ID at capture time** (zero-padded, 3 digits). These IDs are referenced by Phase 7's Evidence coverage table — never renumber, never reuse.

**If cannot reproduce.** Halt and ask the user via `AskUserQuestion`:
- "Gather more evidence — what should I look at next?"
- "Proceed on inference only (risky — debug without repro is unreliable)"
- "Abandon — wait until repro is possible"

Default recommendation: gather more evidence. Debug-on-inference often fixes the wrong thing.

## Phase 2.5 — Regression bisect (conditional fast-path)

When the bug is a regression with a known-good baseline and a scriptable repro, `git bisect run` deterministically locates the offending commit + line-level diff without any LLM reasoning. This phase is a **fast-path evidence augmentation** — it never replaces the hypothesis tournament, only seeds it.

### Gate (all three must hold)

1. **`Started:` field from Phase 1 is not "unknown"** — user supplied a last-good ref / SHA / tag / branch.
2. **`Reproducibility confirmed: yes`** in Phase 2's Evidence Inventory — not partial, not no.
3. **Repro is scriptable** — the orchestrator can produce a single shell command that exits 0 when the bug is absent (good) and non-zero when present (bad). If repro requires interactive input, multiple manual steps, or a long-running service, the repro is not scriptable — skip Phase 2.5.

If any gate fails → skip Phase 2.5 silently and proceed to Phase 3a unchanged. Do not push-notify the skip.

### Dispatch shape

```
Agent(
  subagent_type="bisect-isolator",
  description="Bisect regression for <slug>",
  prompt="repro_command: <shell command, exit 0=good, non-zero=bad>\ngood_ref: <last-good SHA/tag/branch from Phase 1 Started field>\nbad_ref: HEAD\nrepo_root: <abs path>\ntask_id: <RUN>\n$BASE: $Z_HARNESS_PLAN_DIR"
)
```

The orchestrator constructs `repro_command` from Phase 2's repro steps. If Phase 2 captured the repro as a failing test, `repro_command` is typically `cargo test -p <crate> <test_name>` or `python -m pytest <path>::<test>`; if Phase 2 captured it as a CLI invocation, use that verbatim. The repro must be self-contained — bisect will run it ~log₂(N) times across the range.

### Handling the return

Parse the `STATUS:` line:

- **`STATUS: ok`** — bisect found the offending commit. Append a high-confidence evidence entry to the Evidence Inventory:

  ```markdown
  - **EVID-NNN:** (source: bisect) Offending commit `<offending_sha>` introduced the regression between `<good_ref>` and `<bad_ref>`. Files changed: `<list>`. Diff excerpt:
    ```diff
    <capped diff from bisect return>
    ```
  ```

  The `(source: bisect)` tag marks this entry as deterministically derived rather than observationally captured. Subsequent phases treat it the same as any other `EVID-NNN`.

  Then **seed Phase 3a's hypothesis-generation prompts** with the bisect result. Append a `Bisect result (high confidence):` block to the Round 1 prompt (immediately after Evidence Inventory) containing the offending SHA + diff excerpt. This shifts LLM attention from "where is the bug?" to "why did this specific change break things?" — which is the harder question bisect cannot answer mechanically.

  ## Problem
  ## Evidence Inventory
  ## Hypothesis Pool
  ## Test Matrix
  ## Experiment Log
  ## Score Updates
  ## Eliminated Alternatives
  ## Root Cause
  ## Fix Plan
  ## Verification
  ## Post-mortem
  ```
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/round1-orchestrator.md` — pre-dispatch checkpoint of the orchestrator's independent Round 1 hypotheses (contamination mitigation).
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/transcripts/` — consultant transcripts.
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/bisect.log` + `offending-show.txt` + `offending-diff.patch` — Phase 2.5 bisect artifacts (only if Phase 2.5 ran and returned `ok`).
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/diff.patch` — fix diff.
- `$Z_HARNESS_PLAN_DIR/MR-REVIEW.md` — optional, if user opted into MR-style review in Phase 9.

## Phase-visibility matrix (consultant context discipline)

Source of truth for what each subagent dispatch sees. Subagent prompts must never include sections outside the listed scope, and must never receive likelihood buckets or posteriors except where listed.

| Phase | Consultant call | Sections passed | Forbidden | Raw test output? |
|---|---|---|---|---|
| 2.5 (bisect) | bisect-isolator (Haiku, not a consultant) | repro_command, good_ref, bad_ref, repo_root, task_id | likelihood buckets, posteriors, any hypothesis content | N/A — mechanical only |
| 3a (Round 1) | both, MODE `generate-hypotheses-round1` | Problem; Evidence Inventory (incl. bisect EVID if Phase 2.5 produced one); doc-fetcher synthesis; bisect result block if Phase 2.5 returned `ok` | Hypothesis Pool (doesn't exist yet); any orchestrator-internal block; likelihood buckets | No |
| 3b (Round 2) | both, MODE `generate-hypotheses-round2-adversarial` | Problem; Evidence Inventory; Hypothesis Pool (full) | Test Matrix; Experiment Log; Score Updates | No |
| 6 (optional Round 3) | both, MODE `generate-hypotheses-round1` | Problem; Evidence Inventory; eliminated `claim` text + falsifying `discriminating_test` only | priors, likelihoods, posteriors, full Eliminated Alternatives section | No |
| 7 (fix consult) | both, MODE `light-fix` | Problem; Evidence Inventory; winning Hypothesis Pool rows; Experiment Log; draft Root Cause; draft Evidence coverage table | Eliminated Alternatives; Score Updates history | No |

Orchestrator alone reads raw test output and assigns likelihood buckets (Phase 6, step 2). This row never appears in the table.

## Hard rules

- **Never debug without repro.** If repro is impossible and user picks "proceed on inference," document that decision in the Problem section and flag in the Post-mortem Confidence section.
- **Never skip the post-mortem.** Even on a trivial bug — the preventative action-items habit is what makes `/z-debug` different from `/z-fix`.
- **Never skip Codex review on the fix** — the safety gate is non-negotiable.
- **Always emit BOTH Round 1 and Round 2 hypothesis-generation consults** — four subagent calls total during generation (2 in R1 + 2 in R2). Plus a fifth pair in Phase 7 for the fix consult.
- **Likelihood-bucket assignment is orchestrator-only.** Never delegate the `{strongly_falsified, …, strongly_supported}` call to a consultant. Never pass raw test output to a consultant.
- **Orchestrator's Round 1 block MUST be checkpointed to disk** (`archive/<run>/round1-orchestrator.md`) BEFORE consultant dispatch. Re-read from disk at merge time, not from conversation state.
- **Wrong-tool gate (Phase 0) is non-skippable.** If the user already has a hypothesis, exit with a `/z-fix` recommendation — do not proceed.
- **Never proceed past auto-bail thresholds** without explicit user override.
- **Fix-gate is objective and binary.** Opens only when (a) winning hypothesis posterior == `very_high` AND (b) every `EVID-NNN` in the Evidence coverage table has status ∈ `{explained, falsifies_alternative, orthogonal_with_reason}` (zero `unexplained`).
- **Phase 2.5 bisect is fast-path-only.** Bisect never blocks the pipeline, never replaces the hypothesis tournament, and never pre-fills the winning hypothesis. It augments the Evidence Inventory and seeds Phase 3a; the fix-gate still requires full posterior + evidence-coverage convergence.
- **No emojis** anywhere in artifacts.

exec
/bin/zsh -lc "rg -n \"Phase 2\\.5|bisect-isolator|archive/<|archive/\\"'$|'"\\"'$BASE/archive|telemetry|log-phase|DESTRUCTIVE_RE|trap cleanup_bisect|mkdir -p" commands/z-debug.md agents/bisect-isolator.md agents/remote-runner.md' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
commands/z-debug.md:19:4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
commands/z-debug.md:34:     mkdir -p "$Z_HARNESS_PLAN_DIR/archive/$RUN"
commands/z-debug.md:140:## Phase 2.5 — Regression bisect (conditional fast-path)
commands/z-debug.md:148:3. **Repro is scriptable** — the orchestrator can produce a single shell command that exits 0 when the bug is absent (good) and non-zero when present (bad). If repro requires interactive input, multiple manual steps, or a long-running service, the repro is not scriptable — skip Phase 2.5.
commands/z-debug.md:150:If any gate fails → skip Phase 2.5 silently and proceed to Phase 3a unchanged. Do not push-notify the skip.
commands/z-debug.md:156:  subagent_type="bisect-isolator",
commands/z-debug.md:184:  _Phase 2.5 bisect skipped: <reason from STATUS return>._
commands/z-debug.md:201:- **Honor the orchestrator-only likelihood-bucket rule.** The bisect-isolator return is raw mechanical output, not a likelihood assignment. The orchestrator (and only the orchestrator) decides how the bisect result weights subsequent likelihood judgments.
commands/z-debug.md:622:- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/round1-orchestrator.md` — pre-dispatch checkpoint of the orchestrator's independent Round 1 hypotheses (contamination mitigation).
commands/z-debug.md:623:- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/transcripts/` — consultant transcripts.
commands/z-debug.md:624:- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/bisect.log` + `offending-show.txt` + `offending-diff.patch` — Phase 2.5 bisect artifacts (only if Phase 2.5 ran and returned `ok`).
commands/z-debug.md:625:- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/diff.patch` — fix diff.
commands/z-debug.md:634:| 2.5 (bisect) | bisect-isolator (Haiku, not a consultant) | repro_command, good_ref, bad_ref, repo_root, task_id | likelihood buckets, posteriors, any hypothesis content | N/A — mechanical only |
commands/z-debug.md:635:| 3a (Round 1) | both, MODE `generate-hypotheses-round1` | Problem; Evidence Inventory (incl. bisect EVID if Phase 2.5 produced one); doc-fetcher synthesis; bisect result block if Phase 2.5 returned `ok` | Hypothesis Pool (doesn't exist yet); any orchestrator-internal block; likelihood buckets | No |
commands/z-debug.md:649:- **Orchestrator's Round 1 block MUST be checkpointed to disk** (`archive/<run>/round1-orchestrator.md`) BEFORE consultant dispatch. Re-read from disk at merge time, not from conversation state.
commands/z-debug.md:653:- **Phase 2.5 bisect is fast-path-only.** Bisect never blocks the pipeline, never replaces the hypothesis tournament, and never pre-fills the winning hypothesis. It augments the Evidence Inventory and seeds Phase 3a; the fix-gate still requires full posterior + evidence-coverage convergence.
agents/bisect-isolator.md:2:name: bisect-isolator
agents/bisect-isolator.md:3:description: Haiku subagent that drives `git bisect run` between a known-good ref and HEAD using a caller-supplied repro script, then returns the offending commit SHA + line-level diff. Mechanical only — no interpretation of WHY the change broke things. Triggered by /z-debug Phase 2.5 when the bug is a regression with a known-good baseline and the repro is scriptable.
agents/bisect-isolator.md:8:You are a fast, mechanical bisect-runner. The caller (typically `/z-debug` Phase 2.5) has a regression with a known-good ref and a scriptable repro. Your job: run `git bisect`, capture the offending commit + diff, return them. You do NOT reason about WHY the commit broke things — that's the caller's job (Sonnet/Opus).
agents/bisect-isolator.md:17:- `task_id` — opaque identifier (typically the run id) for telemetry.
agents/bisect-isolator.md:38:TOKEN="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" start "tasks/<task-id>" bisect_isolate \
agents/bisect-isolator.md:47:DESTRUCTIVE_RE='rm[[:space:]]+-rf[[:space:]]+(/|~|\$HOME)|git[[:space:]]+push|git[[:space:]]+reset[[:space:]]+--hard[[:space:]]+[^H]|git[[:space:]]+branch[[:space:]]+-D|git[[:space:]]+filter-branch|curl[[:space:]]+-X[[:space:]]*(POST|PUT|DELETE|PATCH)|qtctl[[:space:]]+up[[:space:]]+(?!.*paper)|duckdb(?!.*-readonly).*\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\b|psql.*-c.*\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE)\b|>>?[[:space:]]*~/dev/qt-bot/(state|data|logs)|tee[[:space:]]+~/dev/qt-bot/(state|data|logs)|sed[[:space:]]+-i.*~/dev/qt-bot/(state|data|logs)'
agents/bisect-isolator.md:49:if echo "<repro_command>" | grep -iE "$DESTRUCTIVE_RE" >/dev/null 2>&1; then
agents/bisect-isolator.md:50:  MATCHED="$(echo "<repro_command>" | grep -ioE "$DESTRUCTIVE_RE" | head -1)"
agents/bisect-isolator.md:68:trap cleanup_bisect EXIT
agents/bisect-isolator.md:115:mkdir -p "$BASE/archive/<task-id>"
agents/bisect-isolator.md:122:git bisect run bash -c "<repro_command>" 2>&1 | tee "$BASE/archive/<task-id>/bisect.log"
agents/bisect-isolator.md:136:git show --stat --format=fuller "<offending_sha>" > "$BASE/archive/<task-id>/offending-show.txt"
agents/bisect-isolator.md:137:git show "<offending_sha>" > "$BASE/archive/<task-id>/offending-diff.patch"
agents/bisect-isolator.md:140:head -c 4096 "$BASE/archive/<task-id>/offending-diff.patch" > /tmp/bisect-diff-capped.txt
agents/bisect-isolator.md:164:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" end "$TOKEN" \
agents/bisect-isolator.md:198:- **Always emit start/end telemetry**, even on `refused`.
agents/remote-runner.md:46:TOKEN="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" start "tasks/<task-id>" remote_verify \
agents/remote-runner.md:92:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" end "$TOKEN" \
agents/remote-runner.md:125:- Always emit the start/end telemetry, even on `refused`.

codex
I found one direct spec contradiction already: the orchestrator path still treats `STATUS: refused` as a user-blocking halt even though the spec says every non-ok result must fall through to Phase 3a. I’m checking the agent script snippets now for shell-level correctness.
exec
/bin/zsh -lc "sed -n '180,240p' agents/bisect-isolator.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
  <one paragraph: what bisect found, OR why it was unusable/refused/failed>
DIFF (only if STATUS == ok, capped at 4 KB):
  ```diff
  <git show output, head -c 4096>
  ```
BISECT_LOG: <abs path on local where the tee'd log lives>
ORIG_HEAD_RESTORED: <yes | no — flag for caller if reset failed>
```

If `refused` or `bisect_unusable`: include the reason. Examples: `destructive_repro — found 'rm -rf ~/'`, `good_ref_not_found`, `repro_passes_on_bad_ref`, `repro_fails_on_good_ref`, `dirty_working_tree`, `interpretive_work — bounce to Sonnet/Opus`.

## Hard rules

- **Always run `git bisect reset` in a finally-block.** Even on refusal AFTER `git bisect start`. Never leave the repo in a bisect-in-progress state.
- **Never interpret the offending commit.** Return SHA + diff + files changed. Why-it-broke-things analysis belongs with the caller.
- **Never run bisect with a dirty working tree.** Refuse and ask the caller to stash/commit first.
- **The repro script runs ~log₂(N) times across N commits in the range.** Trust the refusal-grep but document this for callers — they should never pass a script that mutates shared state.
- **Mechanical only.** No reasoning about results beyond "did bisect succeed?" and "here is the SHA + diff."
- **Always emit start/end telemetry**, even on `refused`.
- **No emojis.**

exec
/bin/zsh -lc "nl -ba agents/bisect-isolator.md | sed -n '35,175p' && nl -ba commands/z-debug.md | sed -n '170,205p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
    35	### 1. Telemetry: start event
    36	
    37	```bash
    38	TOKEN="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" start "tasks/<task-id>" bisect_isolate \
    39	  "$(printf '{"id":"%s","good":"%s","bad":"%s","repro":"%s"}' "<task-id>" "<good-ref>" "<bad-ref>" "<repro-command>")")"
    40	```
    41	
    42	### 2. Refusal checks
    43	
    44	Apply the verb-grep to `repro_command` BEFORE touching the repo. Concrete pattern (extended regex, case-insensitive — adapt the home-dir paths to your env):
    45	
    46	```bash
    47	DESTRUCTIVE_RE='rm[[:space:]]+-rf[[:space:]]+(/|~|\$HOME)|git[[:space:]]+push|git[[:space:]]+reset[[:space:]]+--hard[[:space:]]+[^H]|git[[:space:]]+branch[[:space:]]+-D|git[[:space:]]+filter-branch|curl[[:space:]]+-X[[:space:]]*(POST|PUT|DELETE|PATCH)|qtctl[[:space:]]+up[[:space:]]+(?!.*paper)|duckdb(?!.*-readonly).*\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\b|psql.*-c.*\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE)\b|>>?[[:space:]]*~/dev/qt-bot/(state|data|logs)|tee[[:space:]]+~/dev/qt-bot/(state|data|logs)|sed[[:space:]]+-i.*~/dev/qt-bot/(state|data|logs)'
    48	
    49	if echo "<repro_command>" | grep -iE "$DESTRUCTIVE_RE" >/dev/null 2>&1; then
    50	  MATCHED="$(echo "<repro_command>" | grep -ioE "$DESTRUCTIVE_RE" | head -1)"
    51	  # Return STATUS: refused, reason: destructive_repro — found '$MATCHED'
    52	  exit 0
    53	fi
    54	```
    55	
    56	Adjust the `rm -rf` clause if the caller documented `<repo_root>/tmp/` or `<repo_root>/target/` as safe scratch — those paths are exempt by the spec but require an additional `grep -v` whitelist before the destructive grep.
    57	
    58	### 2.5. Trap to guarantee `git bisect reset`
    59	
    60	Install a shell trap IMMEDIATELY after the pre-flight check (step 3) so that ANY early exit — refusal-after-bisect-start, error, signal — still cleans up:
    61	
    62	```bash
    63	cleanup_bisect() {
    64	  local rc=$?
    65	  cd "<repo_root>" 2>/dev/null && git bisect reset >/dev/null 2>&1 || true
    66	  return $rc
    67	}
    68	trap cleanup_bisect EXIT
    69	```
    70	
    71	The trap is idempotent — running `git bisect reset` outside a bisect is a no-op. Never leave a repo in mid-bisect state.
    72	
    73	### 3. Pre-flight: refs exist + repo is clean
    74	
    75	```bash
    76	cd "<repo_root>"
    77	git rev-parse --verify "<good_ref>^{commit}" >/dev/null 2>&1 || exit 11   # 11 = good_ref missing
    78	git rev-parse --verify "<bad_ref>^{commit}"  >/dev/null 2>&1 || exit 12   # 12 = bad_ref missing
    79	git diff --quiet && git diff --cached --quiet || exit 13                  # 13 = working tree dirty
    80	```
    81	
    82	If exit 11 → `STATUS: bisect_unusable`, reason `good_ref_not_found`.
    83	If exit 12 → `STATUS: bisect_unusable`, reason `bad_ref_not_found`.
    84	If exit 13 → `STATUS: refused`, reason `dirty_working_tree — caller must stash/commit before bisect`.
    85	
    86	Capture the original HEAD for restoration: `ORIG_HEAD=$(git rev-parse HEAD)`.
    87	
    88	### 4. Sanity-check the repro inverts across the range
    89	
    90	This is the non-negotiable sanity gate. If the repro doesn't invert, bisect's answer is garbage.
    91	
    92	```bash
    93	# Repro on bad_ref must FAIL (non-zero exit)
    94	git checkout --detach "<bad_ref>" >/dev/null 2>&1
    95	bash -c "<repro_command>" > /tmp/bisect-sanity-bad.log 2>&1
    96	BAD_EXIT=$?
    97	
    98	# Repro on good_ref must PASS (zero exit)
    99	git checkout --detach "<good_ref>" >/dev/null 2>&1
   100	bash -c "<repro_command>" > /tmp/bisect-sanity-good.log 2>&1
   101	GOOD_EXIT=$?
   102	
   103	# Restore
   104	git checkout --detach "$ORIG_HEAD" >/dev/null 2>&1
   105	```
   106	
   107	- If `BAD_EXIT == 0` (repro passes on the bad ref) → `STATUS: bisect_unusable`, reason `repro_passes_on_bad_ref — repro does not reproduce the bug at the reported bad commit`.
   108	- If `GOOD_EXIT != 0` (repro fails on the good ref) → `STATUS: bisect_unusable`, reason `repro_fails_on_good_ref — the bug was present at the supposed good ref, so this is not a regression with this baseline`.
   109	- Both correct → proceed.
   110	
   111	### 5. Run `git bisect run`
   112	
   113	```bash
   114	cd "<repo_root>"
   115	mkdir -p "$BASE/archive/<task-id>"
   116	git bisect start
   117	git bisect bad "<bad_ref>"
   118	git bisect good "<good_ref>"
   119	
   120	# git bisect run treats exit 0 = good, 1-124/126-127 = bad, 125 = skip.
   121	# Repro script's natural 0/non-zero contract maps directly.
   122	git bisect run bash -c "<repro_command>" 2>&1 | tee "$BASE/archive/<task-id>/bisect.log"
   123	BISECT_EXIT=${PIPESTATUS[0]}
   124	```
   125	
   126	Parse the offending SHA from `bisect.log`. `git bisect run` prints a line of the form:
   127	```
   128	<sha> is the first bad commit
   129	```
   130	
   131	If no "first bad commit" line found → `STATUS: failed`, reason `bisect_inconclusive — see bisect.log`. (Most common cause: too many `git bisect skip` returns from exit 125 in the repro script.)
   132	
   133	### 6. Capture diff for the offending commit
   134	
   135	```bash
   136	git show --stat --format=fuller "<offending_sha>" > "$BASE/archive/<task-id>/offending-show.txt"
   137	git show "<offending_sha>" > "$BASE/archive/<task-id>/offending-diff.patch"
   138	
   139	# For the inline return: capped diff
   140	head -c 4096 "$BASE/archive/<task-id>/offending-diff.patch" > /tmp/bisect-diff-capped.txt
   141	```
   142	
   143	`FILES_CHANGED` is parsed from `--stat`:
   144	```bash
   145	git show --stat --format="" "<offending_sha>" | awk 'NF && $1 != "|" {print $1}' | head -50
   146	```
   147	
   148	### 7. Restore the repo (finally-block — always run)
   149	
   150	```bash
   151	git bisect reset >/dev/null 2>&1
   152	# Verify HEAD restored
   153	NEW_HEAD=$(git rev-parse HEAD)
   154	if [ "$NEW_HEAD" != "$ORIG_HEAD" ]; then
   155	  git checkout "$ORIG_HEAD" >/dev/null 2>&1
   156	fi
   157	```
   158	
   159	If `git bisect reset` fails for any reason, surface it in the return SUMMARY — the caller may have a dirty repo to clean up manually.
   160	
   161	### 8. Telemetry: end event
   162	
   163	```bash
   164	bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" end "$TOKEN" \
   165	  "$(printf '{"id":"%s","status":"%s","offending_sha":"%s","files_changed":%d,"subagent_model":"haiku","prompt_chars":%d,"response_chars":%d}' \
   166	     "<task-id>" "$STATUS" "$OFFENDING_SHA" "$N_FILES" "${#PROMPT}" "${#RESPONSE}")"
   167	```
   168	
   169	## Return shape (required)
   170	
   171	```
   172	STATUS: ok | bisect_unusable | refused | failed
   173	TASK: <task-id>
   174	OFFENDING_SHA: <40-char SHA, or empty if STATUS != ok>
   175	FILES_CHANGED:
   170	  ```markdown
   171	  - **EVID-NNN:** (source: bisect) Offending commit `<offending_sha>` introduced the regression between `<good_ref>` and `<bad_ref>`. Files changed: `<list>`. Diff excerpt:
   172	    ```diff
   173	    <capped diff from bisect return>
   174	    ```
   175	  ```
   176	
   177	  The `(source: bisect)` tag marks this entry as deterministically derived rather than observationally captured. Subsequent phases treat it the same as any other `EVID-NNN`.
   178	
   179	  Then **seed Phase 3a's hypothesis-generation prompts** with the bisect result. Append a `Bisect result (high confidence):` block to the Round 1 prompt (immediately after Evidence Inventory) containing the offending SHA + diff excerpt. This shifts LLM attention from "where is the bug?" to "why did this specific change break things?" — which is the harder question bisect cannot answer mechanically.
   180	
   181	- **`STATUS: bisect_unusable`** — repro didn't invert across the range, refs not found, or bisect was inconclusive. Append a one-line note to DEBUG.md Evidence Inventory:
   182	
   183	  ```markdown
   184	  _Phase 2.5 bisect skipped: <reason from STATUS return>._
   185	  ```
   186	
   187	  Proceed to Phase 3a unchanged. Bisect's unusability is informative — `repro_passes_on_bad_ref` may indicate the bug is intermittent (Phase 2's "Reproducibility confirmed" was overclaimed); `repro_fails_on_good_ref` may indicate this is not actually a regression (the "good" baseline already had the bug). Mention this hint in the Phase 3a prompt as context, but do not derive hypotheses from it.
   188	
   189	- **`STATUS: refused`** — caller-side bug (destructive repro script, dirty working tree, interpretive_work request). Halt and ask the user via `AskUserQuestion` how to proceed:
   190	  - "Rewrite repro to avoid the refused condition" — return to Phase 2 to revise.
   191	  - "Skip bisect, proceed to Phase 3a" — record the refusal in DEBUG.md and continue.
   192	  - "Abandon" — log `debug_run_end {status: "abandoned"}` and stop.
   193	
   194	- **`STATUS: failed`** — bisect ran but couldn't converge (typically too many `skip` returns). Treat as `bisect_unusable` for routing purposes; the bisect log path is in the return for caller inspection.
   195	
   196	### Hard limits
   197	
   198	- **Bisect never blocks the pipeline.** All non-`ok` returns fall through to Phase 3a. The phase is a fast-path, not a gate.
   199	- **Bisect never replaces hypothesis generation.** Even on `STATUS: ok` with a single-line diff in the offending commit, Phase 3a–6 still runs. Bisect tells you WHAT changed; hypothesis tournament tells you WHY it broke things. A refactor commit can expose a latent bug elsewhere; Round 1+2 adversarial rounds are still valuable for surfacing this.
   200	- **Bisect's offending SHA does NOT pre-fill the winning hypothesis.** The Phase 6 fix-gate still requires `posterior == very_high` AND zero `unexplained` rows in the Evidence coverage table. The bisect evidence is one input among many.
   201	- **Honor the orchestrator-only likelihood-bucket rule.** The bisect-isolator return is raw mechanical output, not a likelihood assignment. The orchestrator (and only the orchestrator) decides how the bisect result weights subsequent likelihood judgments.
   202	
   203	## Phase 3a — Round 1 hypothesis generation (3 LLMs, parallel, independent)
   204	
   205	**Contamination mitigation:** the orchestrator (Claude main thread) writes its OWN hypothesis block to a checkpoint file BEFORE dispatching the consultants. This prevents the orchestrator from re-reading consultant output and laundering it as "its own" hypothesis at merge time.

exec
/bin/zsh -lc "sed -n '1,120p' agents/remote-runner.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
---
name: remote-runner
description: Haiku subagent that handles MECHANICAL remote work — rsync local repo to a per-(slug, task-id) sandbox on the remote host, run cargo build/check/clean, restart paper qtctl manifests, tail logs, run READ-ONLY DB/disk/log queries against shared state. NOT for interpretive debugging (root-causing a failing test, reasoning about DB results — those need Sonnet/Opus). Triggered by tasks tagged **REMOTE_VERIFY** in TASKS.md.
tools: Bash, Read, Grep, Glob
model: haiku
---

You are a fast, mechanical remote-runner. You take an explicit instruction from the caller, execute it against the remote host (in a sandboxed copy of the repo for builds, or directly for read-only queries), and report pass/fail. You do not reason about results beyond "did the command succeed?" and "here is the output" — interpretive work (DB analysis, root-causing a failing test) goes back to the caller.

## Inputs from caller

- **Task ID** (e.g. `T030`)
- **Slug** (the plan slug, e.g. `expand-sports-ml-active`)
- **Remote host** (default `zeke-pc`)
- **Verify command** — one of these classes (see "Command classification" below for routing):
  - **build/test** — `cargo check -p <crate>` / `cargo build -p <crate>` / `cargo test -p <crate>` / `python <script>`
  - **service control (paper-only)** — `qtctl status` / `qtctl restart <paper-manifest>` (refuse real-money)
  - **logs / disk inspection** — `tail -n <N> <log>` / `grep -iE '<pat>' <log>` / `du -sh <path>` / `df -BG <path>` / `ls <path>`
  - **read-only DB query** — `duckdb -readonly <db> "SELECT …"` / `psql -c "SELECT …"` (refuse anything that mutates — see write-detection grep below)
- **$BASE path** (e.g. `$Z_HARNESS_PLAN_DIR`) — for writing the command log archive.

## Command classification (determines routing)

Classify the incoming verify command into one of two buckets:

- **needs-sandbox** — anything that runs code from the repo (cargo, python scripts living in the repo, etc.). These require the rsync step.
- **read-only-against-shared-state** — log tail/grep, `du`/`df`/`ls`, `duckdb -readonly`, `psql` with a query that contains no write verbs, `qtctl status`. These run directly against shared state on remote and **skip the rsync step entirely** — rsync would be wasted work.

`qtctl restart <paper-manifest>` is a write to shared state (the paper service) but does NOT need the repo — also classified as direct-execute (skip rsync).

When in doubt — sandbox it. Wasted rsync is cheaper than running stale code.

## What you DO NOT do

- **NO write DB queries.** Before executing any `duckdb`/`psql` command, grep the SQL string for write verbs (case-insensitive): `INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY .* FROM|VACUUM`. Any hit → refuse with `STATUS: refused`, reason `db_write_requested`. For `duckdb`, require the `-readonly` flag literally present in the command; refuse if absent.
- **NO real-money operations** (`qtctl up <real-manifest>`, anything that writes prod-trading state). Refuse and ask.
- **NO destructive ops** on remote (`rm -rf` outside the sandbox dir, `truncate`, killing live trader procs). Refuse and ask.
- **NO local builds**. The whole point is to use the remote sandbox.
- **NO interpretive reasoning.** If the caller asks "why did this query return 0 rows?" — refuse with `STATUS: refused`, reason `interpretive_work — bounce to Sonnet/Opus`. Execute and return; do not analyze.

## Procedure

### 1. Telemetry: start event

```bash
TOKEN="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" start "tasks/<task-id>" remote_verify \
  "$(printf '{"id":"%s","cmd":"%s","host":"%s"}' "<task-id>" "<verify-cmd>" "<remote-host>")")"
```

### 2. Refusal checks (run BEFORE any remote execution)

Classify the command (see "Command classification" above). Before running anything:

- If the command contains `duckdb` without `-readonly` → refuse (`db_write_requested`).
- If the command contains `duckdb` or `psql`, grep the SQL string for write verbs (regex above) → refuse on any hit.
- If the command is `qtctl up <manifest>` and `<manifest>` lacks the substring `paper` → refuse (`real_money_operation`).
- If the command contains `rm -rf` outside the sandbox dir → refuse (`destructive_op`).
- If the command requests interpretive analysis (e.g. caller said "explain why X") → refuse (`interpretive_work`).

### 3. Routing — sandbox vs direct

**If classified `read-only-against-shared-state`** — skip the rsync step entirely. Go to step 4 with `EXEC_DIR=$HOME` (or the dir implied by the command's own path arguments).

**If classified `needs-sandbox`** — rsync first:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/remote-sandbox-sync.sh" "<remote-host>" "<slug>" "<task-id>"
```

The sandbox path is `<remote-host>:~/dev/qt-bot-sandbox/<slug>/<task-id>/`. The rsync script honors `.z-harness-rsync-exclude` (target/, .git/, data/, parquet/duckdb files, logs/, state/). `EXEC_DIR=~/dev/qt-bot-sandbox/<slug>/<task-id>`.

If rsync fails — abort with `STATUS: rsync_failed`; capture rsync stderr.

### 4. Run the verify command on remote

```bash
ssh "<remote-host>" "cd $EXEC_DIR && <verify-cmd>" 2>&1 \
  | tee "$BASE/archive/tasks/<task-id>/remote-build.log"
```

Capture the exit code. If exit non-zero, also capture the first 80 lines of any error/warning text (`grep -iE 'error|warning|failed' | head -80`).

### 5. Cargo clean cadence (run BEFORE step 4 if conditions met AND command is cargo)

Only applicable when the verify command is `cargo …` (sandboxed). Maintain a small state file on remote: `~/dev/qt-bot-sandbox/<slug>/.build-counter`. Increment per successful build. When counter reaches 10 OR remote disk has <10 GB free (`df -BG /home | awk 'NR==2{print $4}' | tr -d 'G'`), run `cargo clean` in the sandbox before step 4, then reset counter to 0.

Also: at the START of a fresh `/z-implement-all` invocation (caller-signaled via env var `Z_HARNESS_LOCAL_CARGO_CLEAN=1`), run a one-time `cargo clean` on the LOCAL checkout. This is the only local cargo work this agent does.

### 6. Telemetry: end event

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" end "$TOKEN" \
  "$(printf '{"id":"%s","exit_code":%d,"build_log_path":"%s","subagent_model":"haiku","prompt_chars":%d,"response_chars":%d}' \
     "<task-id>" "$EXIT_CODE" "<log-path>" "${#PROMPT}" "${#RESPONSE}")"
```

### 7. Sandbox cleanup (on success only, sandboxed runs only)

If the run was `needs-sandbox` and `exit_code == 0`, remove the sandbox: `ssh <remote-host> "rm -rf ~/dev/qt-bot-sandbox/<slug>/<task-id>/"`. On failure, leave it for debugging — the user can clean later. For `read-only-against-shared-state` runs, no cleanup needed (no sandbox was created).

## Return shape (required)

```
STATUS: ok | failed | refused | rsync_failed
TASK: <ID>
EXIT_CODE: <int>
BUILD_LOG: <abs path on local where the tee'd log lives>
SUMMARY:
  <one sentence: passed / failed-with-N-errors / refused-because-X>
ERROR_EXCERPT (only if exit_code != 0):
  <first 20 lines of relevant errors, max 800 chars>
```

If `refused`: include the refusal reason. Examples: `db_write_requested`, `duckdb missing -readonly flag`, `real_money_operation`, `destructive_op`, `interpretive_work — bounce to Sonnet/Opus`, `command outside sandbox dir`.

For read-only DB/log queries that succeed, **also include the first ~50 lines of stdout** in the return (under an `OUTPUT:` block, capped at 4 KB) so the caller doesn't need to re-fetch the log file for small queries. For larger results, refer the caller to `BUILD_LOG:`.

## Hard rules

- For `needs-sandbox` runs, never execute anything outside `~/dev/qt-bot-sandbox/<slug>/<task-id>/` on remote (except the cargo clean inside the same dir, and the build-counter state file under `~/dev/qt-bot-sandbox/<slug>/`).

exec
/bin/zsh -lc "printf '%s\\n' 'qtctl up live-manifest' | grep -iE 'qtctl[[:space:]]+up[[:space:]]+(?"'!.*paper)'"' ; printf 'exit=%s\\n' "'$?' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
grep: repetition-operator operand invalid
exit=2

codex
- **BLOCKER** — [commands/z-debug.md:189](/Users/zeke/dev/z-harness/commands/z-debug.md:189): `STATUS: refused` still halts for user input, contradicting the spec and the hard limit at line 198 that all non-`ok` bisect results fall through to Phase 3a. Suggested fix: route `refused` exactly like `bisect_unusable/failed`: record a terse skip/refusal note if desired, then proceed to Phase 3a without AskUserQuestion.

- **MAJOR** — [agents/bisect-isolator.md:47](/Users/zeke/dev/z-harness/agents/bisect-isolator.md:47): `DESTRUCTIVE_RE` uses negative lookahead with `grep -E`, which fails with `grep: repetition-operator operand invalid`, so destructive commands can bypass the refusal check. Suggested fix: use `grep -Pi` where available, or split the checks into POSIX ERE positives plus explicit allow/deny shell conditionals.

- **MAJOR** — [agents/bisect-isolator.md:49](/Users/zeke/dev/z-harness/agents/bisect-isolator.md:49): the destructive-refusal path exits before the end telemetry step, violating the acceptance criterion and the file’s own hard rule that start/end telemetry is always emitted, even on `refused`. Suggested fix: do not `exit` from refusal checks; set `STATUS=refused`, `REASON=...`, emit the required return shape, and funnel all exits through a final telemetry block.

- **MAJOR** — [agents/bisect-isolator.md:93](/Users/zeke/dev/z-harness/agents/bisect-isolator.md:93): the sanity check detaches HEAD before bisect starts, but the `EXIT` trap only runs `git bisect reset`, so an error/signal during sanity checking can leave the repo on `bad_ref` or `good_ref`. Suggested fix: capture `ORIG_HEAD` before any checkout and make the cleanup trap restore it after `git bisect reset` when the current HEAD differs.

Prior MAJOR 2: I would not block this task on `${#PROMPT}` / `${#RESPONSE}` because it matches the existing `remote-runner` convention, but it remains a project-wide telemetry correctness issue.
tokens used
104,954
- **BLOCKER** — [commands/z-debug.md:189](/Users/zeke/dev/z-harness/commands/z-debug.md:189): `STATUS: refused` still halts for user input, contradicting the spec and the hard limit at line 198 that all non-`ok` bisect results fall through to Phase 3a. Suggested fix: route `refused` exactly like `bisect_unusable/failed`: record a terse skip/refusal note if desired, then proceed to Phase 3a without AskUserQuestion.

- **MAJOR** — [agents/bisect-isolator.md:47](/Users/zeke/dev/z-harness/agents/bisect-isolator.md:47): `DESTRUCTIVE_RE` uses negative lookahead with `grep -E`, which fails with `grep: repetition-operator operand invalid`, so destructive commands can bypass the refusal check. Suggested fix: use `grep -Pi` where available, or split the checks into POSIX ERE positives plus explicit allow/deny shell conditionals.

- **MAJOR** — [agents/bisect-isolator.md:49](/Users/zeke/dev/z-harness/agents/bisect-isolator.md:49): the destructive-refusal path exits before the end telemetry step, violating the acceptance criterion and the file’s own hard rule that start/end telemetry is always emitted, even on `refused`. Suggested fix: do not `exit` from refusal checks; set `STATUS=refused`, `REASON=...`, emit the required return shape, and funnel all exits through a final telemetry block.

- **MAJOR** — [agents/bisect-isolator.md:93](/Users/zeke/dev/z-harness/agents/bisect-isolator.md:93): the sanity check detaches HEAD before bisect starts, but the `EXIT` trap only runs `git bisect reset`, so an error/signal during sanity checking can leave the repo on `bad_ref` or `good_ref`. Suggested fix: capture `ORIG_HEAD` before any checkout and make the cleanup trap restore it after `git bisect reset` when the current HEAD differs.

Prior MAJOR 2: I would not block this task on `${#PROMPT}` / `${#RESPONSE}` because it matches the existing `remote-runner` convention, but it remains a project-wide telemetry correctness issue.
