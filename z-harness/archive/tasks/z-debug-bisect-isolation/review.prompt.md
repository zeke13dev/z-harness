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
