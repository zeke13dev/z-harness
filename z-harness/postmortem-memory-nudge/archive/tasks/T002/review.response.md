2026-05-27T05:38:42.401451Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-27T05:38:42.402206Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-27T05:38:42.402217Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-27T05:38:42.402221Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-suggest-memory/SKILL.md: invalid YAML: did not find expected key at line 3 column 35, while parsing a block mapping
2026-05-27T05:38:42.402225Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-27T05:38:42.402228Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-27T05:38:42.402232Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/plugins/cache/personal/z-harness/0.1.0/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.133.0
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR]
reasoning effort: medium
reasoning summaries: none
session id: 019e67f1-3814-7dd2-b1c6-40c1e62b8006
--------
user
You are reviewing code that Claude just wrote for task T002: Add 5th stdout line (DEBUG.md path) for debug parent + conditional spec_path.

Spec (excerpt from SPEC.md):

### `scripts/run-memory-review.sh`

**Existing surface (preserved):**
- Args: `<RUN> <parent_command>`
- Stdout line 1: `STATUS: ready | STATUS: skipped <reason>`
- Stdout lines 2-4 (when ready): absolute paths to cumulative.diff, SPEC.md, TAGS.txt
- Exit 0 always

**Additions:**

1. Accept `parent_command: debug` as a third valid value. For `debug`, skip the `all_tasks_skipped` check, and additionally require `$BASE/DEBUG.md` to exist and be readable. If absent, emit `STATUS: skipped debug_md_missing`.

2. Line 5 (debug parent only): For `parent_command: debug` and `STATUS: ready`, additionally emit a **fifth** stdout line: the absolute path to DEBUG.md. Lines 1-4 remain the existing contract (STATUS / cumulative.diff / SPEC.md / TAGS.txt). Line 5 is debug-only.

3. **spec_path conditional emission:** If `$BASE/SPEC.md` does not exist (fresh `/z-debug` runs may have no SPEC), emit an empty line for line 3 rather than the path.

4. **Gate change:** The orchestrator caller (Phase 10 of `/z-debug`) is responsible for invoking this helper only on the `status: shipped` finalize branch. The helper itself only checks that `$BASE/DEBUG.md` **exists and is readable** (`[[ -r "$DEBUG_MD" ]]`); if not, emit `STATUS: skipped debug_md_missing`.

**Invariants:**
- Always exit 0 (skip is success).
- Never write outside `$BASE/archive/$RUN/`.
- Never mutate INDEX.json or memory files.

Acceptance criteria:
- For parent_command: debug and STATUS: ready, line 5 is absolute path to DEBUG.md
- For all parents, line 3 emits empty line if $BASE/SPEC.md does not exist
- Lines 1-4 remain backward-compatible for implement-all/review-all

Diff (primary artifact — focus your scrutiny on what changed):

```diff
diff --git a/scripts/run-memory-review.sh b/scripts/run-memory-review.sh
index 753525b..f5594fb 100755
--- a/scripts/run-memory-review.sh
+++ b/scripts/run-memory-review.sh
@@ -1,13 +1,14 @@
 #!/usr/bin/env bash
-# Helper called by /z-implement-all and /z-review-all.
+# Helper called by /z-implement-all, /z-review-all, and /z-debug.
 # Encapsulates the review-agent lifecycle skip-conditions and artifact prep.
 #
 # Usage: bash scripts/run-memory-review.sh <RUN> <parent_command>
-#   parent_command: implement-all | review-all
+#   parent_command: implement-all | review-all | debug
 #
 # Exit 0 always (skip is success).
 # Stdout line 1 is always: STATUS: ready | STATUS: skipped <reason>
-# If ready, lines 2-4 are absolute paths to: cumulative.diff, SPEC.md, TAGS.txt
+# If ready, lines 2-4 are absolute paths to: cumulative.diff, SPEC.md (or empty if missing), TAGS.txt
+# Line 5 (debug parent only): absolute path to DEBUG.md
 
 set -euo pipefail
 
@@ -84,6 +85,15 @@ if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
   fi
 fi
 
+# --- Skip-condition 3: debug parent requires DEBUG.md to exist and be readable ---
+if [[ "$PARENT_COMMAND" == "debug" ]]; then
+  DEBUG_MD="$BASE/DEBUG.md"
+  if [[ ! -r "$DEBUG_MD" ]]; then
+    echo "STATUS: skipped debug_md_missing"
+    exit 0
+  fi
+fi
+
 # --- Verify TAGS.txt exists ---
 TAGS_FILE="$REPO_ROOT/docs/llm/TAGS.txt"
 if [[ ! -f "$TAGS_FILE" ]]; then
@@ -105,7 +115,14 @@ set -o pipefail
 # --- Print ready + artifact paths (all absolute) ---
 echo "STATUS: ready"
 echo "$DIFF_FILE"
-echo "$BASE/SPEC.md"
+if [[ -f "$BASE/SPEC.md" ]]; then
+  echo "$BASE/SPEC.md"
+else
+  echo ""
+fi
 echo "$TAGS_FILE"
+if [[ "$PARENT_COMMAND" == "debug" ]]; then
+  echo "$BASE/DEBUG.md"
+fi
 
 exit 0
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

**OUTPUT BUDGET — respect strictly:**
- Total response under **8000 characters**.
- Report **blockers and majors only**. Skip minors and nits unless a "minor" hides a correctness bug — in which case promote it to major.
- One finding per bullet. Two sentences max per finding (one for the problem, one for the fix).
- No re-stating of code already in the diff. No summaries of what the code does. No restating the spec.
- If there are no blockers or majors, respond with exactly: `No blockers or majors found.` (plus an optional 1-line note if something needs the implementer's attention but is below the bar).

codex
I’ll verify the diff against the surrounding script so the review catches interactions outside the shown hunk, especially argument validation and earlier skip paths.
exec
/bin/zsh -lc "sed -n '1,180p' scripts/run-memory-review.sh && rg -n \"run-memory-review|parent_command|memory review\" -S ." in /Users/zeke/dev/z-harness
 succeeded in 0ms:
#!/usr/bin/env bash
# Helper called by /z-implement-all, /z-review-all, and /z-debug.
# Encapsulates the review-agent lifecycle skip-conditions and artifact prep.
#
# Usage: bash scripts/run-memory-review.sh <RUN> <parent_command>
#   parent_command: implement-all | review-all | debug
#
# Exit 0 always (skip is success).
# Stdout line 1 is always: STATUS: ready | STATUS: skipped <reason>
# If ready, lines 2-4 are absolute paths to: cumulative.diff, SPEC.md (or empty if missing), TAGS.txt
# Line 5 (debug parent only): absolute path to DEBUG.md

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "STATUS: skipped missing_args"
  exit 0
fi

RUN="$1"
PARENT_COMMAND="$2"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$REPO_ROOT}}"
LOG_EVENT="$PLUGIN_ROOT/scripts/log-event.sh"

# Resolve plan base dir — must be absolute
BASE="${Z_HARNESS_PLAN_DIR:-}"
if [[ -z "$BASE" ]]; then
  echo "STATUS: skipped no_plan_dir"
  exit 0
fi

# Normalize BASE to an absolute path
if [[ -d "$BASE" ]]; then
  BASE="$(cd "$BASE" && pwd)"
else
  # Directory doesn't exist yet; prefix with REPO_ROOT if relative
  case "$BASE" in
    /*) ;;  # already absolute
    *) BASE="$REPO_ROOT/$BASE" ;;
  esac
fi

RUN_DIR="$BASE/archive/$RUN"
mkdir -p "$RUN_DIR"

# --- Skip-condition 1: empty diff ---
# Resolve a valid base ref: prefer origin/main merge-base, then HEAD~5, then empty-tree.
EMPTY_TREE="4b825dc642cb6eb9a060e54bf8d69288fbee4904"
BASE_REF=""

MERGE_BASE="$(git merge-base HEAD origin/main 2>/dev/null || true)"
if [[ -n "$MERGE_BASE" ]] && git rev-parse --verify "${MERGE_BASE}^{commit}" >/dev/null 2>&1; then
  BASE_REF="$MERGE_BASE"
elif git rev-parse --verify "HEAD~5^{commit}" >/dev/null 2>&1; then
  BASE_REF="HEAD~5"
else
  BASE_REF="$EMPTY_TREE"
fi

# Test emptiness without loading the diff into memory, then stream to file.
if git diff --quiet "${BASE_REF}..HEAD" 2>/dev/null; then
  echo "STATUS: skipped empty_diff"
  if [[ -x "$LOG_EVENT" ]]; then
    bash "$LOG_EVENT" "$RUN" "phase_end" \
      '{"name":"memory_review","skipped":true,"skip_reason":"empty_diff"}' || true
  fi
  exit 0
fi

# --- Skip-condition 2: zero completed tasks and parent is implement-all ---
TASKS_FILE="$BASE/TASKS.md"
if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
  COMPLETED_COUNT="$(grep -c '\[x\]' "$TASKS_FILE" 2>/dev/null || true)"
  COMPLETED_COUNT="${COMPLETED_COUNT:-0}"
  COMPLETED_COUNT="$(printf '%s' "$COMPLETED_COUNT" | tr -d '[:space:]')"
  if [[ "${COMPLETED_COUNT:-0}" -eq 0 ]]; then
    echo "STATUS: skipped all_tasks_skipped"
    if [[ -x "$LOG_EVENT" ]]; then
      bash "$LOG_EVENT" "$RUN" "phase_end" \
        '{"name":"memory_review","skipped":true,"skip_reason":"all_tasks_skipped"}' || true
    fi
    exit 0
  fi
fi

# --- Skip-condition 3: debug parent requires DEBUG.md to exist and be readable ---
if [[ "$PARENT_COMMAND" == "debug" ]]; then
  DEBUG_MD="$BASE/DEBUG.md"
  if [[ ! -r "$DEBUG_MD" ]]; then
    echo "STATUS: skipped debug_md_missing"
    exit 0
  fi
fi

# --- Verify TAGS.txt exists ---
TAGS_FILE="$REPO_ROOT/docs/llm/TAGS.txt"
if [[ ! -f "$TAGS_FILE" ]]; then
  echo "STATUS: skipped tags_missing"
  if [[ -x "$LOG_EVENT" ]]; then
    bash "$LOG_EVENT" "$RUN" "review_agent_failed" \
      '{"reason":"tags_missing"}' || true
  fi
  exit 0
fi

# --- Write cumulative diff (truncated to 5000 lines, streamed to avoid loading into memory) ---
DIFF_FILE="$RUN_DIR/cumulative.diff"
# Disable pipefail to tolerate SIGPIPE when diff output is shorter than 5000 lines.
set +o pipefail
git diff "${BASE_REF}..HEAD" | head -n 5000 > "$DIFF_FILE"
set -o pipefail

# --- Print ready + artifact paths (all absolute) ---
echo "STATUS: ready"
echo "$DIFF_FILE"
if [[ -f "$BASE/SPEC.md" ]]; then
  echo "$BASE/SPEC.md"
else
  echo ""
fi
echo "$TAGS_FILE"
if [[ "$PARENT_COMMAND" == "debug" ]]; then
  echo "$BASE/DEBUG.md"
fi

exit 0
./skills/z-review-all/SKILL.md:364:## Phase 7 — Memory review (auto)
./skills/z-review-all/SKILL.md:366:1. Call `bash scripts/run-memory-review.sh "$RRUN" "review-all"`. Capture stdout.
./skills/z-review-all/SKILL.md:381:     description="Memory review for <slug>",
./skills/z-review-all/SKILL.md:382:     prompt="run_dir: <RUN_DIR>\ncumulative_diff_path: <cumulative.diff path>\nspec_path: $BASE/SPEC.md\ntags_path: docs/llm/TAGS.txt\nindex_path: docs/llm/INDEX.json\nrun_id: <RRUN>\nparent_command: review-all"
./skills/z-review-all/SKILL.md:389:   # Push-notify: "Memory review output was malformed — no valid fenced json block found. Check events.jsonl for review_agent_malformed."
./docs/human/commands.md:10:The command surface is organized around explicit routing, durable artifacts, and a closed-loop memory layer. Planning-family commands collect deterministic route signals, consult `planning-router` only when signals conflict, write `route-decision.md`, emit `plan_route_decision`, and ask the user before switching. Review-family commands preserve evidence separately from promotion artifacts and route actionable findings through `/z-implement-all --tasks`. Both `/z-implement-all` (Phase 9) and `/z-review-all` (Phase 7) close the loop by running `run-memory-review.sh` after each plan completes, dispatching a `review-agent` to surface memory candidates, and presenting them sequentially for user acceptance — accepted candidates are persisted via `/z-suggest-memory --from-candidate-json`. `/z-uplift` adds a tiered bulk-uplift path: it decomposes the repo into components, runs a cross-cutting pass, dispatches per-component audits, produces per-component TASKS.md files, and drives sequential implementation via `/z-implement-all`. `/z-style-init` authors a STYLE.md grounded in the repo's most idiomatic files and a cross-LLM critique; its `--amend` mode mines repeated dismissals from past MR-REVIEW runs to propose new rules. `/z-providers-discover` probes PATH for known LLM CLIs and writes a `providers.json` with interactively-confirmed role bindings. `/z-export` runs per-target adapter scripts to translate z-harness sources into IDE-specific formats under `exports/`.
./docs/human/commands.md:22:- `commands/z-implement-all.md:1` — `z-implement-all` — Orchestrates task queues with fresh subagents, reviewers, and auto memory review (Phase 9).
./docs/human/commands.md:33:- `commands/z-review-all.md:1` — `z-review-all` — Final-gate reviews cumulative implementation against the plan, then auto-runs memory review (Phase 7).
./docs/human/commands.md:45:- `scripts` — Commands rely on shared scripts for version stamping, event logging, phase timing, plan path resolution, memory flattening, remote support, `run-memory-review.sh`, `discover-providers.py`, `export-<target>.py`, and `extract-dismissals.py`.
./docs/human/commands.md:49:- Memory loop — `/z-implement-all` Phase 9 and `/z-review-all` Phase 7 both call `run-memory-review.sh`, dispatch `review-agent`, and route accepted candidates into `/z-suggest-memory --from-candidate-json`. `/z-stats` Phase 4b surfaces `review_agent_call` events so the user can see memory-review history.
./skills/z-implement-all/SKILL.md:588:## Phase 9 — Memory review (auto)
./skills/z-implement-all/SKILL.md:595:   MEMORY_REVIEW_OUT="$(bash scripts/run-memory-review.sh "$RUN" "implement-all")"
./skills/z-implement-all/SKILL.md:627:     description="Memory review for <SLUG_FOR_DESC>",
./skills/z-implement-all/SKILL.md:634:   parent_command: implement-all"
./skills/z-implement-all/SKILL.md:660:     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./skills/z-implement-all/SKILL.md:670:     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./skills/z-implement-all/SKILL.md:677:     "$(printf '{"run":"%s","parent_command":"implement-all","candidates_emitted":0,"accepted":0}' "$RUN")"
./skills/z-implement-all/SKILL.md:700:        "$(printf '{"run":"%s","parent_command":"implement-all","subagent_model":"haiku","subagent_input_tokens":%d,"subagent_output_tokens":%d,"candidates_emitted":%d,"accepted":"<filled-in-later>"}' \
./skills/z-implement-all/SKILL.md:709:      Push-notify: "Memory review produced `<N>` candidate(s) — please review."
./skills/z-stats/SKILL.md:78:Output format per line: `<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input>/<output>`
./docs/llm/skills.json:214:    "run-memory-review.sh gates whether a review-agent dispatch is warranted before any candidate prompt.",
./docs/llm/review-agent.json:7:    "scripts/run-memory-review.sh",
./docs/llm/review-agent.json:16:    {"file": "scripts/run-memory-review.sh", "line": 1, "symbol": "run-memory-review", "kind": "module", "summary": "Skip-condition guard and artifact-prep helper; called before every review-agent dispatch"},
./docs/llm/review-agent.json:30:    "skip-conditions check via run-memory-review.sh before any Agent dispatch (cost guard)",
./docs/llm/review-agent.json:37:    "run-memory-review.sh requires $Z_HARNESS_PLAN_DIR to be set; unset yields STATUS: skipped no_plan_dir",
./docs/llm/review-agent.json:38:    "run-memory-review.sh soft-skips (exit 0) on missing TAGS.txt rather than failing hard",
./docs/human/review-agent.md:4:> Covers source: agents/review-agent.md, scripts/run-memory-review.sh, skills/z-implement-all/SKILL.md, skills/z-review-all/SKILL.md
./docs/human/review-agent.md:10:The agent reasons but does not write. It returns a single fenced JSON block containing candidate objects. The orchestrator owns all writes: it parses the candidates, surfaces them via `AskUserQuestion` prompts, and routes accepted candidates through `/z-suggest-memory`. Before the agent is dispatched, `scripts/run-memory-review.sh` performs skip-condition checks and assembles artifact paths — the script is always called first, and on a non-skip result the orchestrator constructs the agent prompt from its output.
./docs/human/review-agent.md:17:- `scripts/run-memory-review.sh:1` — `run-memory-review` — skip-condition guard and artifact-prep helper; called by both `/z-implement-all` Phase 9 and `/z-review-all` Phase 7
./docs/human/review-agent.md:23:- `z-implement-all` — Phase 9 calls `run-memory-review.sh`, then dispatches `review-agent`, then runs the accept/skip loop
./docs/human/review-agent.md:35:Before dispatching the agent, `scripts/run-memory-review.sh` performs a skip-conditions check:
./docs/human/review-agent.md:93:- `run-memory-review.sh` requires `$Z_HARNESS_PLAN_DIR` to be set; if unset, the script emits `STATUS: skipped no_plan_dir` and exits 0 without error.
./docs/human/review-agent.md:94:- `run-memory-review.sh` soft-skips (exit 0) on missing `docs/llm/TAGS.txt` rather than failing hard; the orchestrator sees `STATUS: skipped tags_missing`.
./docs/human/review-agent.md:114:There is no per-call wall-clock timeout in the current `Agent(...)` infrastructure. If the Haiku subagent call hangs, ctrl-c is the only escape. The parent command's primary-deliverable push-notify has already fired at this point, so ctrl-c aborts only the memory review phase, not the run's main output.
./docs/human/review-agent.md:132:<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input/output>
./docs/human/skills.md:42:- `scripts` — Skills rely on `plan-path.sh`, `log-event.sh`, `log-phase.sh`, `version.sh`, `regenerate-memories-flat.py`, and `run-memory-review.sh` for path resolution, telemetry, version stamping, memory flat-file sync, and memory-review orchestration.
./docs/human/skills.md:57:- Phase 9 (`z-implement-all`) and Phase 7 (`z-review-all`) are soft phases: all failure paths are silent skips — no halt, no retry. They call `run-memory-review.sh` to gate whether a review-agent dispatch is warranted.
./docs/human/scripts.md:4:> Covers source: scripts/log-event.sh, scripts/log-phase.sh, scripts/regenerate-memories-flat.py, scripts/version.sh, scripts/run-memory-review.sh, scripts/check-timeout.sh, scripts/bundle-plugin.sh, scripts/audit-tarball.sh
./docs/human/scripts.md:18:- `scripts/run-memory-review.sh:1` — `run-memory-review.sh` — Gate script called by `/z-implement-all` and `/z-review-all`; evaluates skip conditions (empty diff, zero completed tasks, missing `TAGS.txt`), writes a truncated cumulative diff to the run archive, and prints artifact paths for the review agent.
./docs/human/scripts.md:27:- `skills` — Skills invoke `log-phase.sh` and `log-event.sh` directly from their telemetry steps; `/z-implement-all` and `/z-review-all` call `run-memory-review.sh` to gate the memory-review subagent.
./docs/human/scripts.md:28:- `agents` — Consultant and reviewer agents source `check-timeout.sh` at startup to set `TIMEOUT_CMD` and emit the one-shot timeout availability event; the doc-updater calls `log-phase.sh`/`log-event.sh` for doc-update telemetry; the memory-review agent receives artifact paths from `run-memory-review.sh`.
./docs/human/scripts.md:29:- `review-agent` — `run-memory-review.sh` is the dedicated lifecycle helper for the memory-review agent; it resolves all three artifact paths (`cumulative.diff`, `SPEC.md`, `TAGS.txt`) that the agent requires.
./docs/human/scripts.md:38:- `run-memory-review.sh` uses `set +o pipefail` around the `git diff | head -n 5000` pipeline to avoid SIGPIPE failures when the diff is shorter than 5000 lines.
./docs/human/scripts.md:56:  `bash scripts/run-memory-review.sh "$RUN" implement-all`
./docs/llm/INDEX.json:83:        "scripts/run-memory-review.sh",
./docs/llm/INDEX.json:267:        "scripts/run-memory-review.sh"
./docs/llm/INDEX.json:279:      "summary": "Post-run Haiku subagent that proposes 0-3 candidate memories from a completed /z-implement-all or /z-review-all run. Reads run events, cumulative diff, and SPEC.md; emits structured candidates as a fenced JSON block. Does not write \u2014 orchestrator owns all writes via /z-suggest-memory. Dispatched by scripts/run-memory-review.sh after skip-conditions check (empty diff, zero tasks completed)."
./commands/z-review-all.md:389:## Phase 7 — Memory review (auto)
./commands/z-review-all.md:391:1. Call `bash scripts/run-memory-review.sh "$RRUN" "review-all"`. Capture stdout.
./commands/z-review-all.md:406:     description="Memory review for <slug>",
./commands/z-review-all.md:407:     prompt="run_dir: <RUN_DIR>\ncumulative_diff_path: <cumulative.diff path>\nspec_path: $BASE/SPEC.md\ntags_path: docs/llm/TAGS.txt\nindex_path: docs/llm/INDEX.json\nrun_id: <RRUN>\nparent_command: review-all"
./commands/z-review-all.md:414:   # Push-notify: "Memory review output was malformed — no valid fenced json block found. Check events.jsonl for review_agent_malformed."
./docs/llm/scripts.json:10:    "scripts/run-memory-review.sh",
./docs/llm/scripts.json:21:    {"file": "scripts/run-memory-review.sh", "line": 1, "symbol": "run-memory-review.sh", "kind": "module", "summary": "Gate script for memory-review agent; checks skip conditions, writes cumulative diff, returns artifact paths."},
./docs/llm/scripts.json:35:    "run-memory-review.sh always exits 0; skip conditions are communicated via STATUS: line on stdout.",
./docs/llm/scripts.json:45:    "run-memory-review.sh disables pipefail around git diff | head -n 5000 to tolerate SIGPIPE.",
./docs/llm/commands.json:44:    {"file": "commands/z-implement-all.md", "line": 1, "symbol": "z-implement-all", "kind": "module", "summary": "Orchestrates task queues with fresh subagents, reviewers, and auto memory review (Phase 9)."},
./docs/llm/commands.json:55:    {"file": "commands/z-review-all.md", "line": 1, "symbol": "z-review-all", "kind": "module", "summary": "Final-gate reviews cumulative implementation, then auto-runs memory review (Phase 7)."},
./commands/z-stats.md:78:Output format per line: `<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input>/<output>`
./agents/review-agent.md:22:- `parent_command:` one of `"implement-all"`, `"review-all"`, or `"debug"` (informs what kind of signals to look for)
./agents/review-agent.md:23:- `debug_md_path:` (optional) absolute path to DEBUG.md. Present only when `parent_command: debug`; absent for `implement-all` and `review-all`.
./agents/review-agent.md:25:**Artifact primacy by `parent_command`:** When `parent_command: debug`, `debug_md_path` is the primary artifact the agent reasons over. `spec_path` is supplementary context for recognizing affected invariants. For `implement-all` and `review-all`, `spec_path` is primary and `debug_md_path` is unset.
./agents/review-agent.md:29:1. Read `events.jsonl` from `run_dir`, `cumulative_diff_path`, `tags_path`, and `index_path`. If `parent_command: debug`, also read `debug_md_path` (primary) and `spec_path` if non-empty. Otherwise read `spec_path` (primary). Enumerate existing concept slugs from `index_path` before suggesting a slug in step 3 — prefer matching an existing slug over coining a new one.
./agents/review-agent.md:44:6. **For `parent_command: debug`:** Filter candidates for generalizable invariants, root-cause patterns, and "why we didn't catch it" gaps. Single-run patches and fix-specific minutiae are NOT memories. Reason over `debug_md_path` as the primary signal source; use `spec_path` (if non-empty) only to cross-reference which invariants the root cause violated.
./commands/z-implement-all.md:598:## Phase 9 — Memory review (auto)
./commands/z-implement-all.md:605:   MEMORY_REVIEW_OUT="$(bash scripts/run-memory-review.sh "$RUN" "implement-all")"
./commands/z-implement-all.md:637:     description="Memory review for <SLUG_FOR_DESC>",
./commands/z-implement-all.md:644:   parent_command: implement-all"
./commands/z-implement-all.md:670:     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./commands/z-implement-all.md:680:     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./commands/z-implement-all.md:687:     "$(printf '{"run":"%s","parent_command":"implement-all","candidates_emitted":0,"accepted":0}' "$RUN")"
./commands/z-implement-all.md:710:        "$(printf '{"run":"%s","parent_command":"implement-all","subagent_model":"haiku","subagent_input_tokens":%d,"subagent_output_tokens":%d,"candidates_emitted":%d,"accepted":"<filled-in-later>"}' \
./commands/z-implement-all.md:719:      Push-notify: "Memory review produced `<N>` candidate(s) — please review."
./scripts/run-memory-review.sh:5:# Usage: bash scripts/run-memory-review.sh <RUN> <parent_command>
./scripts/run-memory-review.sh:6:#   parent_command: implement-all | review-all | debug
./scripts/run-memory-review.sh:21:PARENT_COMMAND="$2"
./scripts/run-memory-review.sh:74:if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
./scripts/run-memory-review.sh:89:if [[ "$PARENT_COMMAND" == "debug" ]]; then
./scripts/run-memory-review.sh:124:if [[ "$PARENT_COMMAND" == "debug" ]]; then
./z-harness/postmortem-memory-nudge/BRAINSTORM.md:67:Keeping current silence is worse in one specific way: it lets users believe z-harness is learning when it is mostly skipping. The dangerous ambiguity is "nothing worth remembering" versus "memory review never ran."
./z-harness/postmortem-memory-nudge/BRAINSTORM.md:98:1. **Environment Anemia (The Bash Gate):** `run-memory-review.sh` acts as a silent kill-switch. Because it exits 0 on all skip conditions (missing `Z_HARNESS_PLAN_DIR`, `TAGS.txt`, or an empty diff), the orchestrator never knows if it skipped because "nothing was found" or because "the environment was broken." In remote/headless contexts like `qt-bot`, transient env vars or missing `docs/llm/` files are likely triggering these silent skips.
./z-harness/postmortem-memory-nudge/BRAINSTORM.md:109:- **First-Class Post-Mortem:** Promote Memory Review from a "Phase 9" afterthought to a standalone skill (`/z-postmortem`). This decouples memory generation from the implementation loop and allows for more expensive/capable models (Sonnet/Opus) to run on the full session history, not just the diff.
./z-harness/postmortem-memory-nudge/BRAINSTORM.md:110:- **Visible Heartbeat:** Replace silent skips in `run-memory-review.sh` with a "Status: Skipped" message that is surfaced in the UI. The user needs to know *why* the system didn't look for memories.
./z-harness/postmortem-memory-nudge/SPEC.md:8:event from `scripts/run-memory-review.sh` and the calling SKILL.md phases.
./z-harness/postmortem-memory-nudge/SPEC.md:32:5. Reconcile the agent input contract so `parent_command: debug` is
./z-harness/postmortem-memory-nudge/SPEC.md:50:### `scripts/run-memory-review.sh`
./z-harness/postmortem-memory-nudge/SPEC.md:53:- Args: `<RUN> <parent_command>`
./z-harness/postmortem-memory-nudge/SPEC.md:60:1. Accept `parent_command: debug` as a third valid value (alongside
./z-harness/postmortem-memory-nudge/SPEC.md:72:     "parent_command": "implement-all|review-all|debug",
./z-harness/postmortem-memory-nudge/SPEC.md:92:4. For `parent_command: debug` and `STATUS: ready`, additionally emit a
./z-harness/postmortem-memory-nudge/SPEC.md:97:   mapfile -t LINES < <(bash scripts/run-memory-review.sh "$RUN" "$PARENT")
./z-harness/postmortem-memory-nudge/SPEC.md:102:   DEBUG_MD="${LINES[4]:-}"   # empty unless parent_command == debug
./z-harness/postmortem-memory-nudge/SPEC.md:112:7. **Gate change for `parent_command: debug`** (replaces earlier frontmatter
./z-harness/postmortem-memory-nudge/SPEC.md:141:  `index_path`, `run_id`, `parent_command`
./z-harness/postmortem-memory-nudge/SPEC.md:149:   > When `parent_command: debug`, `debug_md_path` is the primary artifact
./z-harness/postmortem-memory-nudge/SPEC.md:153:3. Add `debug` to the valid `parent_command` enum.
./z-harness/postmortem-memory-nudge/SPEC.md:155:   > For `parent_command: debug`, filter candidates for generalizable
./z-harness/postmortem-memory-nudge/SPEC.md:171:1. Read both `STATUS:` line AND the new contract of `run-memory-review.sh`:
./z-harness/postmortem-memory-nudge/SPEC.md:190:     ("Memory review skipped on `<slug>`: `<skip_reason>`. Fix to re-enable
./z-harness/postmortem-memory-nudge/SPEC.md:209:- Orchestrator never re-runs `run-memory-review.sh` on the same RUN.
./z-harness/postmortem-memory-nudge/SPEC.md:212:  `parent_command` and `slug`; consumers de-dup on the second one.
./z-harness/postmortem-memory-nudge/SPEC.md:219:`parent_command: review-all` is already in use and unchanged.
./z-harness/postmortem-memory-nudge/SPEC.md:223:### `skills/z-debug/SKILL.md` — Phase 10 internal step (memory review)
./z-harness/postmortem-memory-nudge/SPEC.md:240:3. **Helper call:** `bash scripts/run-memory-review.sh "$RUN" "debug"`.
./z-harness/postmortem-memory-nudge/SPEC.md:246:5. **Ready path:** Dispatch review-agent with `parent_command: debug` and
./z-harness/postmortem-memory-nudge/SPEC.md:277:2. Add a "Memory review terminal states (last 10 runs)" section to the
./z-harness/postmortem-memory-nudge/SPEC.md:280:   Memory review terminal states (last 10 runs across all parents):
./z-harness/postmortem-memory-nudge/SPEC.md:286:3. Cross-parent: group by `parent_command` if `--by-parent` flag is passed
./z-harness/postmortem-memory-nudge/SPEC.md:346:- **DRY:** Single helper (`run-memory-review.sh`) handles all three
./z-harness/postmortem-memory-nudge/SPEC.md:347:  `parent_command` values via a small switch. No sibling helpers.
./z-harness/postmortem-memory-nudge/SPEC.md:369:4. `agents/review-agent.md` accepts `parent_command: debug` and the
./z-harness/postmortem-memory-nudge/SPEC.md:376:6. `run-memory-review.sh` stdout contract is forward-compatible: lines 1-4
./z-harness/postmortem-memory-nudge/PLAN.md:24:- **D1** — terminal-state classification lives in `run-memory-review.sh`.
./z-harness/postmortem-memory-nudge/PLAN.md:47:Extend `scripts/run-memory-review.sh` to:
./z-harness/postmortem-memory-nudge/PLAN.md:48:- Accept `parent_command: debug` with new skip condition `debug_not_shipped`.
./z-harness/postmortem-memory-nudge/PLAN.md:51:- Emit DEBUG.md path on stdout line 4 when `parent_command: debug` and
./z-harness/postmortem-memory-nudge/PLAN.md:58:- Add `debug` to `parent_command` enum.
./z-harness/postmortem-memory-nudge/PLAN.md:59:- Document the "primary artifact by parent_command" rule.
./z-harness/postmortem-memory-nudge/PLAN.md:60:- Add the `parent_command: debug` candidate-generation guidance
./z-harness/postmortem-memory-nudge/PLAN.md:79:- Call helper with `parent_command: debug`. Parse with `mapfile`.
./z-harness/postmortem-memory-nudge/PLAN.md:80:- Dispatch review-agent with `parent_command: debug` and `debug_md_path`
./z-harness/postmortem-memory-nudge/PLAN.md:113:  parent_command values.
./z-harness/postmortem-memory-nudge/PLAN.md:124:| Helper-script argument creep | Refuse logic beyond skip + classify | SPEC §`run-memory-review.sh` |
./z-harness/postmortem-memory-nudge/PLAN.md:127:| Agent prompt complexity for spec-vs-debug | Explicit "primary by parent_command" rule | Phase B |
./z-harness/postmortem-memory-nudge/TASKS.md:7:## T001 [x] — Extend `run-memory-review.sh` to accept `parent_command: debug`
./z-harness/postmortem-memory-nudge/TASKS.md:8:- **Files:** scripts/run-memory-review.sh
./z-harness/postmortem-memory-nudge/TASKS.md:11:  - `parent_command: debug` is a recognized 3rd value alongside `implement-all` and `review-all`.
./z-harness/postmortem-memory-nudge/TASKS.md:18:- **Files:** scripts/run-memory-review.sh
./z-harness/postmortem-memory-nudge/TASKS.md:21:  - For `parent_command: debug` and `STATUS: ready`, line 5 is the absolute path to DEBUG.md.
./z-harness/postmortem-memory-nudge/TASKS.md:28:- **Files:** scripts/run-memory-review.sh
./z-harness/postmortem-memory-nudge/TASKS.md:31:  - Every skip path emits exactly one `memory_review_terminal` event with payload `{state, skip_reason, parent_command, candidates: 0, accepted: 0, slug}`.
./z-harness/postmortem-memory-nudge/TASKS.md:32:  - STATUS → terminal-state mapping from SPEC §`run-memory-review.sh` is implemented (`empty_diff`/`all_tasks_skipped`/`debug_md_missing` → `not_applicable`; `tags_missing`/`no_plan_dir`/`missing_args` → `skipped_broken_context`).
./z-harness/postmortem-memory-nudge/TASKS.md:38:## T004 [x] — Update `agents/review-agent.md` input contract for `parent_command: debug`
./z-harness/postmortem-memory-nudge/TASKS.md:42:  - `parent_command` enum extended with `debug`.
./z-harness/postmortem-memory-nudge/TASKS.md:44:  - Input contract explicitly states: "When `parent_command: debug`, `debug_md_path` is primary; `spec_path` is supplementary. Otherwise spec_path is primary and debug_md_path is unset."
./z-harness/postmortem-memory-nudge/TASKS.md:46:  - Candidate-generation guidance adds: "For `parent_command: debug`, filter for generalizable invariants and root-cause patterns; single-run patches are NOT memories."
./z-harness/postmortem-memory-nudge/TASKS.md:66:  - `parent_command: review-all` unchanged.
./z-harness/postmortem-memory-nudge/TASKS.md:85:  - Phase 10's `status: shipped` finalize branch invokes `bash scripts/run-memory-review.sh "$RUN" "debug"`.
./z-harness/postmortem-memory-nudge/TASKS.md:86:  - Parses stdout with `mapfile`; on `STATUS: ready` dispatches review-agent with `parent_command: debug`, `debug_md_path` from line 5, `spec_path` from line 3 (may be empty), `cumulative_diff_path` from line 2, `tags_path` from line 4.
./z-harness/postmortem-memory-nudge/TASKS.md:99:  - Aggregation groups by terminal state, sub-counts by `skip_reason` and `parent_command`.
./z-harness/postmortem-memory-nudge/TASKS.md:101:  - Output section titled "Memory review terminal states (last 10 runs)" appears after existing Phase 4 content.
./z-harness/postmortem-memory-nudge/archive/20260527T041952Z-postmortem-memory-nudge/phase1-scaffolding.md:20:  `scripts/run-memory-review.sh`.
./z-harness/postmortem-memory-nudge/archive/20260527T041952Z-postmortem-memory-nudge/phase1-scaffolding.md:36:- scripts/run-memory-review.sh
./z-harness/postmortem-memory-nudge/archive/20260527T041952Z-postmortem-memory-nudge/phase1-scaffolding.md:57:there means the post-run memory review will hard-skip on z-harness runs
./z-harness/postmortem-memory-nudge/archive/20260527T041952Z-postmortem-memory-nudge/phase1-scaffolding.md:58:against qt-bot (run-memory-review.sh requires TAGS.txt + INDEX.json).
./exports/agy/prompts/z-review-all.md:389:## Phase 7 — Memory review (auto)
./exports/agy/prompts/z-review-all.md:391:1. Call `bash scripts/run-memory-review.sh "$RRUN" "review-all"`. Capture stdout.
./exports/agy/prompts/z-review-all.md:406:     description="Memory review for <slug>",
./exports/agy/prompts/z-review-all.md:407:     prompt="run_dir: <RUN_DIR>\ncumulative_diff_path: <cumulative.diff path>\nspec_path: $BASE/SPEC.md\ntags_path: docs/llm/TAGS.txt\nindex_path: docs/llm/INDEX.json\nrun_id: <RRUN>\nparent_command: review-all"
./exports/agy/prompts/z-review-all.md:414:   # Push-notify: "Memory review output was malformed — no valid fenced json block found. Check events.jsonl for review_agent_malformed."
./z-harness/archive/tasks/T004/review.prompt.md:1:You are reviewing code that Claude just wrote for task T004: Author scripts/run-memory-review.sh per SPEC.md — bash helper that runs skip-condition checks, captures cumulative diff, prints STATUS line + paths for orchestrator to dispatch the review-agent.
./z-harness/archive/tasks/T004/review.prompt.md:4:From scripts/run-memory-review.sh section of SPEC.md:
./z-harness/archive/tasks/T004/review.prompt.md:8:Signature: `bash scripts/run-memory-review.sh <RUN> <parent_command>`
./z-harness/archive/tasks/T004/review.prompt.md:10:Where `<parent_command>` is `implement-all` or `review-all`.
./z-harness/archive/tasks/T004/review.prompt.md:17:   - Parse `$BASE/TASKS.md`; count `[x]`. If zero AND parent_command is `implement-all` → skip with `skip_reason: all_tasks_skipped`, exit 0.
./z-harness/archive/tasks/T004/review.prompt.md:29:- Prints `STATUS: skipped all_tasks_skipped` and exits 0 when TASKS.md has zero `[x]` and parent_command is implement-all.
./z-harness/archive/tasks/T004/review.prompt.md:36:diff --git a/Users/zeke/dev/z-harness/scripts/run-memory-review.sh b/Users/zeke/dev/z-harness/scripts/run-memory-review.sh
./z-harness/archive/tasks/T004/review.prompt.md:40:+++ b/Users/zeke/dev/z-harness/scripts/run-memory-review.sh
./z-harness/archive/tasks/T004/review.prompt.md:46:+# Usage: bash scripts/run-memory-review.sh <RUN> <parent_command>
./z-harness/archive/tasks/T004/review.prompt.md:47:+#   parent_command: implement-all | review-all
./z-harness/archive/tasks/T004/review.prompt.md:56:+  echo "usage: run-memory-review.sh <RUN> <parent_command>" >&2
./z-harness/archive/tasks/T004/review.prompt.md:61:+PARENT_COMMAND="$2"
./z-harness/archive/tasks/T004/review.prompt.md:70:+  echo "run-memory-review.sh: Z_HARNESS_PLAN_DIR is not set" >&2
./z-harness/archive/tasks/T004/review.prompt.md:92:+if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/decisions.md:5:  - **A. In `run-memory-review.sh`** — emit a single `memory_review_terminal` event with `state: not_applicable|skipped_broken_context|ran_empty|needs_user` *before* exiting. Orchestrator post-dispatch states (`ran_empty`, `needs_user`) are emitted by the SKILL.md callers.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/decisions.md:12:  - **A. New `memory_review_terminal` event** with payload `{state, skip_reason?, parent_command, candidates?, accepted?}`. Coexists with existing `phase_end`, `review_agent_failed`, `review_agent_malformed`, `memory_candidates_ready`.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/decisions.md:34:  - **A. YES — add Phase 9b in `skills/z-debug/SKILL.md`** that calls `run-memory-review.sh "$RUN" "debug"` after the Post-mortem section is written, then dispatches review-agent with DEBUG.md added to its input set.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/decisions.md:37:- **Consult? YES.** Trigger: cross-module change (review-agent + run-memory-review.sh + skills/z-debug/SKILL.md); affects parent_command enum (new value `debug`); algorithmic choice (do we feed DEBUG.md sections separately or as a single artifact?).
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/decisions.md:39:## D6. Should `run-memory-review.sh` learn `debug` parent_command, or do we make a sibling helper?
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/decisions.md:41:  - **A. Extend `run-memory-review.sh`** with `parent_command: debug` — skip-conditions adjust (no TASKS.md `[x]` check; instead require DEBUG.md `status: shipped`).
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/decisions.md:49:  - B. Replace `spec_path` with `debug_md_path` when parent_command == debug.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/decisions.md:63:  - B. Bake the check into `run-memory-review.sh` as a remote-aware probe.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:8:event from `scripts/run-memory-review.sh` and the calling SKILL.md phases.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:32:5. Reconcile the agent input contract so `parent_command: debug` is
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:50:### `scripts/run-memory-review.sh`
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:53:- Args: `<RUN> <parent_command>`
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:60:1. Accept `parent_command: debug` as a third valid value (alongside
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:72:     "parent_command": "implement-all|review-all|debug",
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:92:4. For `parent_command: debug` and `STATUS: ready`, additionally emit a
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:97:   mapfile -t LINES < <(bash scripts/run-memory-review.sh "$RUN" "$PARENT")
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:102:   DEBUG_MD="${LINES[4]:-}"   # empty unless parent_command == debug
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:112:7. **Gate change for `parent_command: debug`** (replaces earlier frontmatter
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:141:  `index_path`, `run_id`, `parent_command`
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:149:   > When `parent_command: debug`, `debug_md_path` is the primary artifact
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:153:3. Add `debug` to the valid `parent_command` enum.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:155:   > For `parent_command: debug`, filter candidates for generalizable
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:171:1. Read both `STATUS:` line AND the new contract of `run-memory-review.sh`:
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:190:     ("Memory review skipped on `<slug>`: `<skip_reason>`. Fix to re-enable
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:209:- Orchestrator never re-runs `run-memory-review.sh` on the same RUN.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:212:  `parent_command` and `slug`; consumers de-dup on the second one.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:219:`parent_command: review-all` is already in use and unchanged.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:223:### `skills/z-debug/SKILL.md` — Phase 10 internal step (memory review)
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:240:3. **Helper call:** `bash scripts/run-memory-review.sh "$RUN" "debug"`.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:246:5. **Ready path:** Dispatch review-agent with `parent_command: debug` and
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:277:2. Add a "Memory review terminal states (last 10 runs)" section to the
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:280:   Memory review terminal states (last 10 runs across all parents):
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:286:3. Cross-parent: group by `parent_command` if `--by-parent` flag is passed
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:346:- **DRY:** Single helper (`run-memory-review.sh`) handles all three
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:347:  `parent_command` values via a small switch. No sibling helpers.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:369:4. `agents/review-agent.md` accepts `parent_command: debug` and the
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/SPEC.md:376:6. `run-memory-review.sh` stdout contract is forward-compatible: lines 1-4
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/PLAN.md:24:- **D1** — terminal-state classification lives in `run-memory-review.sh`.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/PLAN.md:47:Extend `scripts/run-memory-review.sh` to:
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/PLAN.md:48:- Accept `parent_command: debug` with new skip condition `debug_not_shipped`.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/PLAN.md:51:- Emit DEBUG.md path on stdout line 4 when `parent_command: debug` and
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/PLAN.md:58:- Add `debug` to `parent_command` enum.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/PLAN.md:59:- Document the "primary artifact by parent_command" rule.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/PLAN.md:60:- Add the `parent_command: debug` candidate-generation guidance
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/PLAN.md:79:- Call helper with `parent_command: debug`. Parse with `mapfile`.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/PLAN.md:80:- Dispatch review-agent with `parent_command: debug` and `debug_md_path`
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/PLAN.md:113:  parent_command values.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/PLAN.md:124:| Helper-script argument creep | Refuse logic beyond skip + classify | SPEC §`run-memory-review.sh` |
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/PLAN.md:127:| Agent prompt complexity for spec-vs-debug | Explicit "primary by parent_command" rule | Phase B |
./z-harness/archive/tasks/T004/review.response.md:124:/bin/zsh -lc "nl -ba scripts/run-memory-review.sh | sed -n '1,120p'" in /Users/zeke/dev/z-harness
./z-harness/archive/tasks/T004/review.response.md:126:    88	### `scripts/run-memory-review.sh`
./z-harness/archive/tasks/T004/review.response.md:130:    92	Signature: `bash scripts/run-memory-review.sh <RUN> <parent_command>`
./z-harness/archive/tasks/T004/review.response.md:132:    94	Where `<parent_command>` is `implement-all` or `review-all`.
./z-harness/archive/tasks/T004/review.response.md:139:   101	   - Parse `$BASE/TASKS.md`; count `[x]`. If zero AND parent_command is `implement-all` → skip with `skip_reason: all_tasks_skipped`, exit 0.
./z-harness/archive/tasks/T004/review.response.md:150:   137	Insert a new `## Phase 9 — Memory review (auto)` section **AFTER** the existing Finalize block (which currently ends ~line 605) and **AFTER** the existing finalize push-notify, **BEFORE** the "Hard rules" / closing section.
./z-harness/archive/tasks/T004/review.response.md:153:   140	1. Call `bash scripts/run-memory-review.sh "$RUN" "implement-all"`. Capture stdout.
./z-harness/archive/tasks/T004/review.response.md:160:   147	     description="Memory review for <slug>",
./z-harness/archive/tasks/T004/review.response.md:161:   148	     prompt="run_dir: <RUN_DIR>\ncumulative_diff_path: <PATH>\nspec_path: <BASE>/SPEC.md\ntags_path: docs/llm/TAGS.txt\nrun_id: <RUN>\nparent_command: implement-all"
./z-harness/archive/tasks/T004/review.response.md:169:   201	- **Tags-file collision.** If `docs/llm/TAGS.txt` is missing entirely (e.g. fresh repo), `run-memory-review.sh` soft-skips with `skip_reason: tags_missing`. Orchestrator does NOT auto-create TAGS.txt — that's `/z-suggest-memory`'s Phase 0 responsibility.
./z-harness/archive/tasks/T004/review.response.md:179:     5	# Usage: bash scripts/run-memory-review.sh <RUN> <parent_command>
./z-harness/archive/tasks/T004/review.response.md:180:     6	#   parent_command: implement-all | review-all
./z-harness/archive/tasks/T004/review.response.md:189:    15	  echo "usage: run-memory-review.sh <RUN> <parent_command>" >&2
./z-harness/archive/tasks/T004/review.response.md:194:    20	PARENT_COMMAND="$2"
./z-harness/archive/tasks/T004/review.response.md:203:    29	  echo "run-memory-review.sh: Z_HARNESS_PLAN_DIR is not set" >&2
./z-harness/archive/tasks/T004/review.response.md:225:    51	if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
./z-harness/archive/tasks/T004/review.response.md:376:1. **Major** [scripts/run-memory-review.sh:37](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:37>)  
./z-harness/archive/tasks/T004/review.response.md:380:2. **Major** [scripts/run-memory-review.sh:38](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:38>) and [scripts/run-memory-review.sh:80](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:80>)  
./z-harness/archive/tasks/T004/review.response.md:384:3. **Major** [scripts/run-memory-review.sh:27](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:27>), [scripts/run-memory-review.sh:33](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:33>), [scripts/run-memory-review.sh:85](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:85>)  
./z-harness/archive/tasks/T004/review.response.md:388:4. **Major** [scripts/run-memory-review.sh:14](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:14>) and [scripts/run-memory-review.sh:28](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:28>)  
./z-harness/archive/tasks/T004/review.response.md:392:5. **Minor** [scripts/run-memory-review.sh:57](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:57>)  
./z-harness/archive/tasks/T004/review.response.md:396:6. **Minor** [scripts/run-memory-review.sh:65](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:65>)  
./z-harness/archive/tasks/T004/review.response.md:400:7. **Minor** [scripts/run-memory-review.sh:20](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:20>)  
./z-harness/archive/tasks/T004/review.response.md:401:   `parent_command` is not validated. A typo silently disables the `implement-all` skip behavior and can dispatch review when all tasks were skipped.  
./z-harness/archive/tasks/T004/review.response.md:404:8. **Nit / hardening** [scripts/run-memory-review.sh:19](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:19>)  
./z-harness/archive/tasks/T004/review.response.md:413:1. **Major** [scripts/run-memory-review.sh:37](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:37>)  
./z-harness/archive/tasks/T004/review.response.md:417:2. **Major** [scripts/run-memory-review.sh:38](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:38>) and [scripts/run-memory-review.sh:80](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:80>)  
./z-harness/archive/tasks/T004/review.response.md:421:3. **Major** [scripts/run-memory-review.sh:27](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:27>), [scripts/run-memory-review.sh:33](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:33>), [scripts/run-memory-review.sh:85](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:85>)  
./z-harness/archive/tasks/T004/review.response.md:425:4. **Major** [scripts/run-memory-review.sh:14](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:14>) and [scripts/run-memory-review.sh:28](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:28>)  
./z-harness/archive/tasks/T004/review.response.md:429:5. **Minor** [scripts/run-memory-review.sh:57](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:57>)  
./z-harness/archive/tasks/T004/review.response.md:433:6. **Minor** [scripts/run-memory-review.sh:65](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:65>)  
./z-harness/archive/tasks/T004/review.response.md:437:7. **Minor** [scripts/run-memory-review.sh:20](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:20>)  
./z-harness/archive/tasks/T004/review.response.md:438:   `parent_command` is not validated. A typo silently disables the `implement-all` skip behavior and can dispatch review when all tasks were skipped.  
./z-harness/archive/tasks/T004/review.response.md:441:8. **Nit / hardening** [scripts/run-memory-review.sh:19](</Users/zeke/dev/z-harness/scripts/run-memory-review.sh:19>)  
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/phase3-decisions-final.md:10:### D1. Compute 4-state terminal in `run-memory-review.sh`
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/phase3-decisions-final.md:12:  into a giant `if [[ parent_command == … ]]` tree (implement-all wants
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/phase3-decisions-final.md:15:- **Mitigation accepted:** Use a single switch on `$PARENT_COMMAND` for the
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/phase3-decisions-final.md:35:    "parent_command": "implement-all|review-all|debug",
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/phase3-decisions-final.md:49:  - Update the review-agent prompt to explicitly say: "for parent_command=debug,
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/phase3-decisions-final.md:60:  > When `parent_command: debug`, `debug_md_path` is the primary artifact;
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/phase3-decisions-final.md:71:    saw "memory review skipped: tags_missing" once on this slug, don't fire
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/phase3-decisions-final.md:84:- D1 enables D5: same helper handles `parent_command: debug` cleanly.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/TASKS.md:7:## T001 — Extend `run-memory-review.sh` to accept `parent_command: debug`
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/TASKS.md:8:- **Files:** scripts/run-memory-review.sh
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/TASKS.md:11:  - `parent_command: debug` is a recognized 3rd value alongside `implement-all` and `review-all`.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/TASKS.md:18:- **Files:** scripts/run-memory-review.sh
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/TASKS.md:21:  - For `parent_command: debug` and `STATUS: ready`, line 5 is the absolute path to DEBUG.md.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/TASKS.md:28:- **Files:** scripts/run-memory-review.sh
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/TASKS.md:31:  - Every skip path emits exactly one `memory_review_terminal` event with payload `{state, skip_reason, parent_command, candidates: 0, accepted: 0, slug}`.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/TASKS.md:32:  - STATUS → terminal-state mapping from SPEC §`run-memory-review.sh` is implemented (`empty_diff`/`all_tasks_skipped`/`debug_md_missing` → `not_applicable`; `tags_missing`/`no_plan_dir`/`missing_args` → `skipped_broken_context`).
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/TASKS.md:38:## T004 — Update `agents/review-agent.md` input contract for `parent_command: debug`
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/TASKS.md:42:  - `parent_command` enum extended with `debug`.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/TASKS.md:44:  - Input contract explicitly states: "When `parent_command: debug`, `debug_md_path` is primary; `spec_path` is supplementary. Otherwise spec_path is primary and debug_md_path is unset."
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/TASKS.md:46:  - Candidate-generation guidance adds: "For `parent_command: debug`, filter for generalizable invariants and root-cause patterns; single-run patches are NOT memories."
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/TASKS.md:66:  - `parent_command: review-all` unchanged.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/TASKS.md:85:  - Phase 10's `status: shipped` finalize branch invokes `bash scripts/run-memory-review.sh "$RUN" "debug"`.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/TASKS.md:86:  - Parses stdout with `mapfile`; on `STATUS: ready` dispatches review-agent with `parent_command: debug`, `debug_md_path` from line 5, `spec_path` from line 3 (may be empty), `cumulative_diff_path` from line 2, `tags_path` from line 4.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/TASKS.md:99:  - Aggregation groups by terminal state, sub-counts by `skip_reason` and `parent_command`.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/TASKS.md:101:  - Output section titled "Memory review terminal states (last 10 runs)" appears after existing Phase 4 content.
./exports/agy/prompts/skill-z-stats.md:78:Output format per line: `<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input>/<output>`
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/phase1-context.md:5:**Phase 9 (z-implement-all) and Phase 7 (z-review-all) call `run-memory-review.sh`:**
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/phase1-context.md:6:- `scripts/run-memory-review.sh "$RUN" "<implement-all|review-all>"`
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/phase1-context.md:9:**Current STATUS vocabulary** ([scripts/run-memory-review.sh](scripts/run-memory-review.sh)):
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/phase1-context.md:43:1. New `parent_command: debug` accepted by `run-memory-review.sh` and `agents/review-agent.md`.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/phase1-context.md:44:2. New `run-memory-review.sh` skip-condition appropriate for /z-debug (e.g., don't require TASKS.md `[x]` count).
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z-postmortem-memory-nudge/phase1-context.md:60:`run-memory-review.sh` reads:
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z/transcripts/001-gemini-plan-review.prompt.md:6:- run-memory-review.sh: emit memory_review_terminal events with 4-state taxonomy
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z/transcripts/001-gemini-plan-review.prompt.md:7:- review-agent.md: add optional debug_md_path and parent_command:debug support
./z-harness/archive/20260527T050549Z-harness-distribution-strategy/transcripts/001-gemini-decisions-memory-review.prompt.md:11:**Current scripts/run-memory-review.sh skip-condition vocabulary:**
./z-harness/archive/20260527T050549Z-harness-distribution-strategy/transcripts/001-gemini-decisions-memory-review.prompt.md:21:### D1. Compute 4-state terminal in run-memory-review.sh vs in SKILL.md callers
./z-harness/archive/20260527T050549Z-harness-distribution-strategy/transcripts/001-gemini-decisions-memory-review.prompt.md:22:- Tentative: In `run-memory-review.sh` (single source of skip-condition logic)
./z-harness/archive/20260527T050549Z-harness-distribution-strategy/transcripts/001-gemini-decisions-memory-review.prompt.md:27:- Tentative: New event with {state, skip_reason?, parent_command, candidates?, accepted?}
./z-harness/archive/20260527T050549Z-harness-distribution-strategy/transcripts/001-gemini-decisions-memory-review.prompt.md:32:- Tentative: YES — Phase 9b in skills/z-debug/SKILL.md, calls run-memory-review.sh with parent_command=debug
./z-harness/archive/20260527T050549Z-harness-distribution-strategy/transcripts/001-gemini-decisions-memory-review.prompt.md:37:- Tentative: Optional additive (spec_path unchanged when parent_command=debug, add debug_md_path)
./z-harness/archive/20260527T050549Z-harness-distribution-strategy/transcripts/001-gemini-decisions-memory-review.prompt.md:38:- Alternative: Replace spec_path with debug_md_path when parent_command=debug
./z-harness/archive/20260527T050549Z-harness-distribution-strategy/transcripts/001-gemini-decisions-memory-review.prompt.md:49:**run-memory-review.sh skip conditions (current):**
./z-harness/archive/20260527T050549Z-harness-distribution-strategy/transcripts/001-gemini-decisions-memory-review.prompt.md:62:if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
./z-harness/archive/20260527T050549Z-harness-distribution-strategy/transcripts/001-gemini-decisions-memory-review.prompt.md:105:- parent_command: "implement-all" | "review-all"
./z-harness/archive/20260527T050549Z-harness-distribution-strategy/transcripts/001-gemini-decisions-memory-review.prompt.md:107:Currently no provision for `debug_md_path` when parent_command=debug.
./z-harness/archive/20260527T050549Z-harness-distribution-strategy/transcripts/001-gemini-decisions-memory-review.prompt.md:116:- Calls `bash scripts/run-memory-review.sh "$RUN" "implement-all"`
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z/transcripts/001-gemini-plan-review.response.md:7:**2. Missing edge cases in `run-memory-review.sh`**
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z/transcripts/001-gemini-plan-review.response.md:9:- **Stdout line collision:** Line 4 is currently `$TAGS_FILE`. If `parent_command:debug` emits `DEBUG.md` on line 4, it breaks the parser contract in existing callers. Append `DEBUG.md` to line 5 instead.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z/transcripts/001-gemini-plan-review.response.md:10:- **Double-logging skips:** If `run-memory-review.sh` emits the new `memory_review_terminal` for skips, and the orchestrator *also* emits it, you get duplicates. The orchestrator should own ALL terminal logging based on the script's `STATUS: skipped` stdout.
./z-harness/postmortem-memory-nudge/archive/20260527T045853Z/transcripts/001-gemini-plan-review.response.md:13:- **Wrong base ref:** `run-memory-review.sh` guesses the base ref (`origin/main` or `HEAD~5`). For `/z-debug`, this is wrong and will pull in unrelated workspace changes. It MUST be passed `$PRE_FIX_SHA` (captured in `z-debug` Phase 7) to generate an accurate `cumulative.diff`.
./z-harness/postmortem-memory-nudge/archive/tasks/T001/diff.patch:1:diff --git a/scripts/run-memory-review.sh b/scripts/run-memory-review.sh
./z-harness/postmortem-memory-nudge/archive/tasks/T001/diff.patch:3:--- a/scripts/run-memory-review.sh
./z-harness/postmortem-memory-nudge/archive/tasks/T001/diff.patch:4:+++ b/scripts/run-memory-review.sh
./z-harness/postmortem-memory-nudge/archive/tasks/T001/diff.patch:11: # Usage: bash scripts/run-memory-review.sh <RUN> <parent_command>
./z-harness/postmortem-memory-nudge/archive/tasks/T001/diff.patch:12:-#   parent_command: implement-all | review-all
./z-harness/postmortem-memory-nudge/archive/tasks/T001/diff.patch:13:+#   parent_command: implement-all | review-all | debug
./z-harness/postmortem-memory-nudge/archive/tasks/T001/diff.patch:17:@@ -84,6 +84,15 @@ if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
./z-harness/postmortem-memory-nudge/archive/tasks/T001/diff.patch:22:+if [[ "$PARENT_COMMAND" == "debug" ]]; then
./z-harness/postmortem-memory-nudge/archive/tasks/T004/review/review.prompt.md:1:You are reviewing code that Claude just wrote for task T004: Update agents/review-agent.md input contract for parent_command: debug.
./z-harness/postmortem-memory-nudge/archive/tasks/T004/review/review.prompt.md:8:- Input fields: `run_dir`, `cumulative_diff_path`, `spec_path`, `tags_path`, `index_path`, `run_id`, `parent_command`
./z-harness/postmortem-memory-nudge/archive/tasks/T004/review/review.prompt.md:15:   > When `parent_command: debug`, `debug_md_path` is the primary artifact the agent reasons over. `spec_path` is supplementary context for recognizing affected invariants. For `implement-all` and `review-all`, `spec_path` is primary and `debug_md_path` is unset.
./z-harness/postmortem-memory-nudge/archive/tasks/T004/review/review.prompt.md:16:3. Add `debug` to the valid `parent_command` enum.
./z-harness/postmortem-memory-nudge/archive/tasks/T004/review/review.prompt.md:18:   > For `parent_command: debug`, filter candidates for generalizable invariants, root-cause patterns, and "why we didn't catch it" gaps. Single-run patches and fix-specific minutiae are NOT memories.
./z-harness/postmortem-memory-nudge/archive/tasks/T004/review/review.response.md:6:The diff added `debug_md_path` to inputs, documented it as primary for debug runs (lines 25-26), and added step 6 guidance for debug filtering. However, step 1 of the Procedure still reads only `events.jsonl`, `cumulative_diff_path`, `spec_path`, `tags_path`, `index_path` — it omits `debug_md_path` entirely, creating ambiguity about whether the agent should read this new primary artifact when `parent_command: debug`.
./z-harness/postmortem-memory-nudge/archive/tasks/T004/review/review.response.md:8:**Fix:** Update step 1 to branch on `parent_command`. Suggested wording:
./z-harness/postmortem-memory-nudge/archive/tasks/T004/review/review.response.md:9:"1. Read `events.jsonl` from `run_dir`, `cumulative_diff_path`, `tags_path`, and `index_path`. If `parent_command: debug`, also read `debug_md_path` (primary) and `spec_path` if non-empty. Otherwise read `spec_path` (primary). Enumerate existing concept slugs from `index_path` before suggesting a slug in step 3 — prefer matching an existing slug over coining a new one."
./z-harness/postmortem-memory-nudge/archive/tasks/T004/review/review.response.md:14:- `debug` added to `parent_command` enum ✓
./exports/agy/prompts/z-stats.md:78:Output format per line: `<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input>/<output>`
./z-harness/postmortem-memory-nudge/archive/tasks/T004/diff-v1.patch:22:-- `parent_command:` one of `"implement-all"` or `"review-all"` (informs what kind of signals to look for)
./z-harness/postmortem-memory-nudge/archive/tasks/T004/diff-v1.patch:23:+- `parent_command:` one of `"implement-all"`, `"review-all"`, or `"debug"` (informs what kind of signals to look for)
./z-harness/postmortem-memory-nudge/archive/tasks/T004/diff-v1.patch:24:+- `debug_md_path:` (optional) absolute path to DEBUG.md. Present only when `parent_command: debug`; absent for `implement-all` and `review-all`.
./z-harness/postmortem-memory-nudge/archive/tasks/T004/diff-v1.patch:26:+**Artifact primacy by `parent_command`:** When `parent_command: debug`, `debug_md_path` is the primary artifact the agent reasons over. `spec_path` is supplementary context for recognizing affected invariants. For `implement-all` and `review-all`, `spec_path` is primary and `debug_md_path` is unset.
./z-harness/postmortem-memory-nudge/archive/tasks/T004/diff-v1.patch:34:+6. **For `parent_command: debug`:** Filter candidates for generalizable invariants, root-cause patterns, and "why we didn't catch it" gaps. Single-run patches and fix-specific minutiae are NOT memories. Reason over `debug_md_path` as the primary signal source; use `spec_path` (if non-empty) only to cross-reference which invariants the root cause violated.
./z-harness/archive/tasks/T001/review.prompt.md:1:You are reviewing code that Claude just wrote for task T001: Extend run-memory-review.sh to accept parent_command: debug.
./z-harness/archive/tasks/T001/review.prompt.md:3:Spec (excerpt from z-harness/postmortem-memory-nudge/SPEC.md, section "scripts/run-memory-review.sh"):
./z-harness/archive/tasks/T001/review.prompt.md:6:- Args: `<RUN> <parent_command>`
./z-harness/archive/tasks/T001/review.prompt.md:13:1. Accept `parent_command: debug` as a third valid value (alongside
./z-harness/archive/tasks/T001/review.prompt.md:26:     "parent_command": "implement-all|review-all|debug",
./z-harness/archive/tasks/T001/review.prompt.md:46:4. For `parent_command: debug` and `STATUS: ready`, additionally emit a
./z-harness/archive/tasks/T001/review.prompt.md:59:7. **Gate change for `parent_command: debug`** The helper itself only checks that
./z-harness/archive/tasks/T001/review.prompt.md:71:- parent_command: debug recognized 3rd value alongside implement-all and review-all
./z-harness/archive/tasks/T001/review.prompt.md:77:diff --git a/scripts/run-memory-review.sh b/scripts/run-memory-review.sh
./z-harness/archive/tasks/T001/review.prompt.md:79:--- a/scripts/run-memory-review.sh
./z-harness/archive/tasks/T001/review.prompt.md:80:+++ b/scripts/run-memory-review.sh
./z-harness/archive/tasks/T001/review.prompt.md:87: # Usage: bash scripts/run-memory-sh <RUN> <parent_command>
./z-harness/archive/tasks/T001/review.prompt.md:88:-#   parent_command: implement-all | review-all
./z-harness/archive/tasks/T001/review.prompt.md:89:+#   parent_command: implement-all | review-all | debug
./z-harness/archive/tasks/T001/review.prompt.md:93:@@ -84,6 +84,15 @@ if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
./z-harness/archive/tasks/T001/review.prompt.md:98:+if [[ "$PARENT_COMMAND" == "debug" ]]; then
./z-harness/archive/tasks/T001/review.prompt.md:116:# Usage: bash scripts/run-memory-review.sh <RUN> <parent_command>
./z-harness/archive/tasks/T001/review.prompt.md:117:#   parent_command: implement-all | review-all | debug
./z-harness/archive/tasks/T001/review.prompt.md:131:PARENT_COMMAND="$2"
./z-harness/archive/tasks/T001/review.prompt.md:184:if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
./z-harness/archive/tasks/T001/review.prompt.md:199:if [[ "$PARENT_COMMAND" == "debug" ]]; then
./z-harness/postmortem-memory-nudge/archive/tasks/T004/delta-v2.patch:24:++1. Read `events.jsonl` from `run_dir`, `cumulative_diff_path`, `tags_path`, and `index_path`. If `parent_command: debug`, also read `debug_md_path` (primary) and `spec_path` if non-empty. Otherwise read `spec_path` (primary). Enumerate existing concept slugs from `index_path` before suggesting a slug in step 3 — prefer matching an existing slug over coining a new one.
./z-harness/postmortem-memory-nudge/archive/tasks/T004/diff.patch:22:-- `parent_command:` one of `"implement-all"` or `"review-all"` (informs what kind of signals to look for)
./z-harness/postmortem-memory-nudge/archive/tasks/T004/diff.patch:23:+- `parent_command:` one of `"implement-all"`, `"review-all"`, or `"debug"` (informs what kind of signals to look for)
./z-harness/postmortem-memory-nudge/archive/tasks/T004/diff.patch:24:+- `debug_md_path:` (optional) absolute path to DEBUG.md. Present only when `parent_command: debug`; absent for `implement-all` and `review-all`.
./z-harness/postmortem-memory-nudge/archive/tasks/T004/diff.patch:26:+**Artifact primacy by `parent_command`:** When `parent_command: debug`, `debug_md_path` is the primary artifact the agent reasons over. `spec_path` is supplementary context for recognizing affected invariants. For `implement-all` and `review-all`, `spec_path` is primary and `debug_md_path` is unset.
./z-harness/postmortem-memory-nudge/archive/tasks/T004/diff.patch:31:+1. Read `events.jsonl` from `run_dir`, `cumulative_diff_path`, `tags_path`, and `index_path`. If `parent_command: debug`, also read `debug_md_path` (primary) and `spec_path` if non-empty. Otherwise read `spec_path` (primary). Enumerate existing concept slugs from `index_path` before suggesting a slug in step 3 — prefer matching an existing slug over coining a new one.
./z-harness/postmortem-memory-nudge/archive/tasks/T004/diff.patch:39:+6. **For `parent_command: debug`:** Filter candidates for generalizable invariants, root-cause patterns, and "why we didn't catch it" gaps. Single-run patches and fix-specific minutiae are NOT memories. Reason over `debug_md_path` as the primary signal source; use `spec_path` (if non-empty) only to cross-reference which invariants the root cause violated.
./z-harness/archive/tasks/T001/review.response.md:20:You are reviewing code that Claude just wrote for task T001: Extend run-memory-review.sh to accept parent_command: debug.
./z-harness/archive/tasks/T001/review.response.md:22:Spec (excerpt from z-harness/postmortem-memory-nudge/SPEC.md, section "scripts/run-memory-review.sh"):
./z-harness/archive/tasks/T001/review.response.md:25:- Args: `<RUN> <parent_command>`
./z-harness/archive/tasks/T001/review.response.md:32:1. Accept `parent_command: debug` as a third valid value (alongside
./z-harness/archive/tasks/T001/review.response.md:45:     "parent_command": "implement-all|review-all|debug",
./z-harness/archive/tasks/T001/review.response.md:65:4. For `parent_command: debug` and `STATUS: ready`, additionally emit a
./z-harness/archive/tasks/T001/review.response.md:78:7. **Gate change for `parent_command: debug`** The helper itself only checks that
./z-harness/archive/tasks/T001/review.response.md:90:- parent_command: debug recognized 3rd value alongside implement-all and review-all
./z-harness/archive/tasks/T001/review.response.md:96:diff --git a/scripts/run-memory-review.sh b/scripts/run-memory-review.sh
./z-harness/archive/tasks/T001/review.response.md:98:--- a/scripts/run-memory-review.sh
./z-harness/archive/tasks/T001/review.response.md:99:+++ b/scripts/run-memory-review.sh
./z-harness/archive/tasks/T001/review.response.md:106: # Usage: bash scripts/run-memory-sh <RUN> <parent_command>
./z-harness/archive/tasks/T001/review.response.md:107:-#   parent_command: implement-all | review-all
./z-harness/archive/tasks/T001/review.response.md:108:+#   parent_command: implement-all | review-all | debug
./z-harness/archive/tasks/T001/review.response.md:112:@@ -84,6 +84,15 @@ if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
./z-harness/archive/tasks/T001/review.response.md:117:+if [[ "$PARENT_COMMAND" == "debug" ]]; then
./z-harness/archive/tasks/T001/review.response.md:135:# Usage: bash scripts/run-memory-review.sh <RUN> <parent_command>
./z-harness/archive/tasks/T001/review.response.md:136:#   parent_command: implement-all | review-all | debug
./z-harness/archive/tasks/T001/review.response.md:150:PARENT_COMMAND="$2"
./z-harness/archive/tasks/T001/review.response.md:203:if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
./z-harness/archive/tasks/T001/review.response.md:218:if [[ "$PARENT_COMMAND" == "debug" ]]; then
./z-harness/archive/tasks/T001/review.response.md:271:- **Blocker**: `scripts/run-memory-review.sh:13-118` does not emit exactly one `memory_review_terminal` event per invocation; several exits emit none, and existing skips still emit `phase_end` or `review_agent_failed`. Add a single terminal-event helper and call it before every `exit 0`, with the required payload and mapped `state`/`skip_reason`.
./z-harness/archive/tasks/T001/review.response.md:273:- **Blocker**: `scripts/run-memory-review.sh:99-105` still emits `review_agent_failed` for `tags_missing`, which the spec explicitly reserves for orchestrator agent-dispatch failures. Replace this with `memory_review_terminal` using `state: skipped_broken_context` and `skip_reason: tags_missing`.
./z-harness/archive/tasks/T001/review.response.md:275:- **Major**: `scripts/run-memory-review.sh:113-117` does not print the debug-only fifth stdout line containing the absolute `DEBUG.md` path when `parent_command` is `debug` and status is ready. Track `DEBUG_MD` for debug runs and echo it after `TAGS.txt` only for debug.
./z-harness/archive/tasks/T001/review.response.md:277:- **Major**: `scripts/run-memory-review.sh:116` always prints `$BASE/SPEC.md`, even when the file does not exist. Emit an empty third line when `[[ ! -f "$BASE/SPEC.md" ]]`.
./z-harness/archive/tasks/T001/review.response.md:279:- **Major**: `scripts/run-memory-review.sh:89-95` skips `debug_md_missing` without emitting the required terminal event. Emit `memory_review_terminal` with `state: not_applicable` and `skip_reason: debug_md_missing`.
./z-harness/archive/tasks/T001/review.response.md:281:- **Major**: `scripts/run-memory-review.sh:37-38` allows `RUN` path traversal, so a run value like `../../outside` can make the script create/write outside `$BASE/archive/$RUN/`’s intended archive boundary. Validate `RUN` as a safe slug/path segment or resolve `RUN_DIR` and assert it remains under `$BASE/archive/` before `mkdir` or writing `cumulative.diff`.
./z-harness/archive/tasks/T001/review.response.md:284:- **Blocker**: `scripts/run-memory-review.sh:13-118` does not emit exactly one `memory_review_terminal` event per invocation; several exits emit none, and existing skips still emit `phase_end` or `review_agent_failed`. Add a single terminal-event helper and call it before every `exit 0`, with the required payload and mapped `state`/`skip_reason`.
./z-harness/archive/tasks/T001/review.response.md:286:- **Blocker**: `scripts/run-memory-review.sh:99-105` still emits `review_agent_failed` for `tags_missing`, which the spec explicitly reserves for orchestrator agent-dispatch failures. Replace this with `memory_review_terminal` using `state: skipped_broken_context` and `skip_reason: tags_missing`.
./z-harness/archive/tasks/T001/review.response.md:288:- **Major**: `scripts/run-memory-review.sh:113-117` does not print the debug-only fifth stdout line containing the absolute `DEBUG.md` path when `parent_command` is `debug` and status is ready. Track `DEBUG_MD` for debug runs and echo it after `TAGS.txt` only for debug.
./z-harness/archive/tasks/T001/review.response.md:290:- **Major**: `scripts/run-memory-review.sh:116` always prints `$BASE/SPEC.md`, even when the file does not exist. Emit an empty third line when `[[ ! -f "$BASE/SPEC.md" ]]`.
./z-harness/archive/tasks/T001/review.response.md:292:- **Major**: `scripts/run-memory-review.sh:89-95` skips `debug_md_missing` without emitting the required terminal event. Emit `memory_review_terminal` with `state: not_applicable` and `skip_reason: debug_md_missing`.
./z-harness/archive/tasks/T001/review.response.md:294:- **Major**: `scripts/run-memory-review.sh:37-38` allows `RUN` path traversal, so a run value like `../../outside` can make the script create/write outside `$BASE/archive/$RUN/`’s intended archive boundary. Validate `RUN` as a safe slug/path segment or resolve `RUN_DIR` and assert it remains under `$BASE/archive/` before `mkdir` or writing `cumulative.diff`.
./z-harness/postmortem-memory-nudge/archive/tasks/T002/diff.patch:1:diff --git a/scripts/run-memory-review.sh b/scripts/run-memory-review.sh
./z-harness/postmortem-memory-nudge/archive/tasks/T002/diff.patch:3:--- a/scripts/run-memory-review.sh
./z-harness/postmortem-memory-nudge/archive/tasks/T002/diff.patch:4:+++ b/scripts/run-memory-review.sh
./z-harness/postmortem-memory-nudge/archive/tasks/T002/diff.patch:11: # Usage: bash scripts/run-memory-review.sh <RUN> <parent_command>
./z-harness/postmortem-memory-nudge/archive/tasks/T002/diff.patch:12:-#   parent_command: implement-all | review-all
./z-harness/postmortem-memory-nudge/archive/tasks/T002/diff.patch:13:+#   parent_command: implement-all | review-all | debug
./z-harness/postmortem-memory-nudge/archive/tasks/T002/diff.patch:23:@@ -84,6 +85,15 @@ if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
./z-harness/postmortem-memory-nudge/archive/tasks/T002/diff.patch:28:+if [[ "$PARENT_COMMAND" == "debug" ]]; then
./z-harness/postmortem-memory-nudge/archive/tasks/T002/diff.patch:50:+if [[ "$PARENT_COMMAND" == "debug" ]]; then
./z-harness/postmortem-memory-nudge/archive/20260527T042238Z-postmortem-memory-nudge/phase1-scaffolding.md:10:- **scripts** — `scripts/run-memory-review.sh` is the gate script; exits 0 always. Skip conditions: missing `Z_HARNESS_PLAN_DIR`, empty diff, zero completed tasks (when parent=implement-all), TAGS.txt missing. Writes `cumulative.diff` on ready path. `scripts/regenerate-memories-flat.py` atomically regenerates `MEMORIES-FLAT.md` from `docs/llm/*.json` memories arrays.
./z-harness/postmortem-memory-nudge/archive/20260527T042238Z-postmortem-memory-nudge/phase1-scaffolding.md:29:- The skip condition for `no_plan_dir` (missing `Z_HARNESS_PLAN_DIR`) is the FIRST check in run-memory-review.sh — if the env var isn't set, the whole phase silently bails.
./z-harness/postmortem-memory-nudge/archive/20260527T042238Z-postmortem-memory-nudge/transcripts/codex-ideator.txt:17:Keeping current silence is worse in one specific way: it lets users believe z-harness is learning when it is mostly skipping. The dangerous ambiguity is “nothing worth remembering” versus “memory review never ran.”
./z-harness/postmortem-memory-nudge/archive/20260527T042238Z-postmortem-memory-nudge/transcripts/gemini-ideator.txt:6:1.  **Environment Anemia (The Bash Gate):** `run-memory-review.sh` acts as a silent kill-switch. Because it exits 0 on all skip conditions (missing `Z_HARNESS_PLAN_DIR`, `TAGS.txt`, or an empty diff), the orchestrator never knows if it skipped because "nothing was found" or because "the environment was broken." In remote/headless contexts like `qt-bot`, transient env vars or missing `docs/llm/` files are likely triggering these silent skips.
./z-harness/postmortem-memory-nudge/archive/20260527T042238Z-postmortem-memory-nudge/transcripts/gemini-ideator.txt:17:- **First-Class Post-Mortem:** Promote Memory Review from a "Phase 9" afterthought to a standalone skill (`/z-postmortem`). This decouples memory generation from the implementation loop and allows for more expensive/capable models (Sonnet/Opus) to run on the full session history, not just the diff.
./z-harness/postmortem-memory-nudge/archive/20260527T042238Z-postmortem-memory-nudge/transcripts/gemini-ideator.txt:18:- **Visible Heartbeat:** Replace silent skips in `run-memory-review.sh` with a "Status: Skipped" message that is surfaced in the UI. The user needs to know *why* the system didn't look for memories.
./exports/agy/prompts/review-agent.md:20:- `parent_command:` one of `"implement-all"` or `"review-all"` (informs what kind of signals to look for)
./exports/agy/prompts/z-implement-all.md:599:## Phase 9 — Memory review (auto)
./exports/agy/prompts/z-implement-all.md:606:   MEMORY_REVIEW_OUT="$(bash scripts/run-memory-review.sh "$RUN" "implement-all")"
./exports/agy/prompts/z-implement-all.md:638:     description="Memory review for <SLUG_FOR_DESC>",
./exports/agy/prompts/z-implement-all.md:645:   parent_command: implement-all"
./exports/agy/prompts/z-implement-all.md:671:     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./exports/agy/prompts/z-implement-all.md:681:     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./exports/agy/prompts/z-implement-all.md:688:     "$(printf '{"run":"%s","parent_command":"implement-all","candidates_emitted":0,"accepted":0}' "$RUN")"
./exports/agy/prompts/z-implement-all.md:711:        "$(printf '{"run":"%s","parent_command":"implement-all","subagent_model":"haiku","subagent_input_tokens":%d,"subagent_output_tokens":%d,"candidates_emitted":%d,"accepted":"<filled-in-later>"}' \
./exports/agy/prompts/z-implement-all.md:720:      Push-notify: "Memory review produced `<N>` candidate(s) — please review."
./z-harness/archive/codex-decisions-memory-review/transcripts/001-codex-bundled-decisions.prompt.md:10:- Tentative: In `run-memory-review.sh` (single source of skip-condition logic)
./z-harness/archive/codex-decisions-memory-review/transcripts/001-codex-bundled-decisions.prompt.md:14:- Tentative: New `memory_review_terminal` event with {state, skip_reason?, parent_command, candidates?, accepted?}
./z-harness/archive/codex-decisions-memory-review/transcripts/001-codex-bundled-decisions.prompt.md:18:- Tentative: YES — Phase 9b in skills/z-debug/SKILL.md, calls run-memory-review.sh with parent_command=debug, feeds DEBUG.md as extra context. /z-debug post-mortems contain the densest memory signal in the harness; not dispatching is leaving signal on the floor.
./z-harness/archive/codex-decisions-memory-review/transcripts/001-codex-bundled-decisions.prompt.md:23:- Alternative: Replace `spec_path` with `debug_md_path` when parent_command=debug
./z-harness/archive/codex-decisions-memory-review/transcripts/001-codex-bundled-decisions.prompt.md:32:Current `run-memory-review.sh` skip conditions (lines 47-96):
./z-harness/archive/codex-decisions-memory-review/transcripts/001-codex-bundled-decisions.prompt.md:41:run_dir, cumulative_diff_path, spec_path, tags_path, index_path, run_id, parent_command
./z-harness/archive/codex-decisions-memory-review/transcripts/001-codex-bundled-decisions.prompt.md:43:Currently no provision for debug_md_path when parent_command=debug.
./z-harness/archive/codex-decisions-memory-review/transcripts/001-codex-bundled-decisions.prompt.md:50:- D6: Extend run-memory-review.sh for parent_command=debug vs sibling helper
./z-harness/archive/codex-decisions-memory-review/transcripts/001-codex-bundled-decisions.response.md:2:- Recommendation: Compute the 4-state terminal taxonomy in `run-memory-review.sh`. Keep SKILL.md callers as thin dispatchers that pass context and parent metadata.
./z-harness/archive/codex-decisions-memory-review/transcripts/001-codex-bundled-decisions.response.md:12:- Recommendation: Yes, add Phase 9b to `/z-debug` and call `run-memory-review.sh` with `parent_command=debug` plus `DEBUG.md` context.
./z-harness/archive/codex-decisions-memory-review/transcripts/001-codex-bundled-decisions.response.md:18:- Risk: Agent prompts may start treating both `spec_path` and `debug_md_path` as equally authoritative unless the contract says which artifact is primary per `parent_command`.
./exports/agy/prompts/skill-z-implement-all.md:589:## Phase 9 — Memory review (auto)
./exports/agy/prompts/skill-z-implement-all.md:596:   MEMORY_REVIEW_OUT="$(bash scripts/run-memory-review.sh "$RUN" "implement-all")"
./exports/agy/prompts/skill-z-implement-all.md:628:     description="Memory review for <SLUG_FOR_DESC>",
./exports/agy/prompts/skill-z-implement-all.md:635:   parent_command: implement-all"
./exports/agy/prompts/skill-z-implement-all.md:661:     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./exports/agy/prompts/skill-z-implement-all.md:671:     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./exports/agy/prompts/skill-z-implement-all.md:678:     "$(printf '{"run":"%s","parent_command":"implement-all","candidates_emitted":0,"accepted":0}' "$RUN")"
./exports/agy/prompts/skill-z-implement-all.md:701:        "$(printf '{"run":"%s","parent_command":"implement-all","subagent_model":"haiku","subagent_input_tokens":%d,"subagent_output_tokens":%d,"candidates_emitted":%d,"accepted":"<filled-in-later>"}' \
./exports/agy/prompts/skill-z-implement-all.md:710:      Push-notify: "Memory review produced `<N>` candidate(s) — please review."
./exports/agy/prompts/skill-z-review-all.md:364:## Phase 7 — Memory review (auto)
./exports/agy/prompts/skill-z-review-all.md:366:1. Call `bash scripts/run-memory-review.sh "$RRUN" "review-all"`. Capture stdout.
./exports/agy/prompts/skill-z-review-all.md:381:     description="Memory review for <slug>",
./exports/agy/prompts/skill-z-review-all.md:382:     prompt="run_dir: <RUN_DIR>\ncumulative_diff_path: <cumulative.diff path>\nspec_path: $BASE/SPEC.md\ntags_path: docs/llm/TAGS.txt\nindex_path: docs/llm/INDEX.json\nrun_id: <RRUN>\nparent_command: review-all"
./exports/agy/prompts/skill-z-review-all.md:389:   # Push-notify: "Memory review output was malformed — no valid fenced json block found. Check events.jsonl for review_agent_malformed."
./exports/codex/AGENTS.md:2039:- `parent_command:` one of `"implement-all"` or `"review-all"` (informs what kind of signals to look for)
./exports/codex/prompts/z-review-all.md:386:## Phase 7 — Memory review (auto)
./exports/codex/prompts/z-review-all.md:388:1. Call `bash scripts/run-memory-review.sh "$RRUN" "review-all"`. Capture stdout.
./exports/codex/prompts/z-review-all.md:403:     description="Memory review for <slug>",
./exports/codex/prompts/z-review-all.md:404:     prompt="run_dir: <RUN_DIR>\ncumulative_diff_path: <cumulative.diff path>\nspec_path: $BASE/SPEC.md\ntags_path: docs/llm/TAGS.txt\nindex_path: docs/llm/INDEX.json\nrun_id: <RRUN>\nparent_command: review-all"
./exports/codex/prompts/z-review-all.md:411:   # Push-notify: "Memory review output was malformed — no valid fenced json block found. Check events.jsonl for review_agent_malformed."
./exports/codex/prompts/z-stats-skill.md:75:Output format per line: `<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input>/<output>`
./z-harness/plans/tiered-quality-uplift/archive/20260526T055704Z-review/cumulative.diff:176:       "summary": "Post-run Haiku subagent that proposes 0-3 candidate memories from a completed /z-implement-all or /z-review-all run. Reads run events, cumulative diff, and SPEC.md; emits structured candidates as a fenced JSON block. Does not write \u2014 orchestrator owns all writes via /z-suggest-memory. Dispatched by scripts/run-memory-review.sh after skip-conditions check (empty diff, zero tasks completed)."
./exports/codex/prompts/z-review-all-skill.md:361:## Phase 7 — Memory review (auto)
./exports/codex/prompts/z-review-all-skill.md:363:1. Call `bash scripts/run-memory-review.sh "$RRUN" "review-all"`. Capture stdout.
./exports/codex/prompts/z-review-all-skill.md:378:     description="Memory review for <slug>",
./exports/codex/prompts/z-review-all-skill.md:379:     prompt="run_dir: <RUN_DIR>\ncumulative_diff_path: <cumulative.diff path>\nspec_path: $BASE/SPEC.md\ntags_path: docs/llm/TAGS.txt\nindex_path: docs/llm/INDEX.json\nrun_id: <RRUN>\nparent_command: review-all"
./exports/codex/prompts/z-review-all-skill.md:386:   # Push-notify: "Memory review output was malformed — no valid fenced json block found. Check events.jsonl for review_agent_malformed."
./exports/codex/prompts/z-stats.md:75:Output format per line: `<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input>/<output>`
./exports/codex/prompts/z-implement-all.md:596:## Phase 9 — Memory review (auto)
./exports/codex/prompts/z-implement-all.md:603:   MEMORY_REVIEW_OUT="$(bash scripts/run-memory-review.sh "$RUN" "implement-all")"
./exports/codex/prompts/z-implement-all.md:635:     description="Memory review for <SLUG_FOR_DESC>",
./exports/codex/prompts/z-implement-all.md:642:   parent_command: implement-all"
./exports/codex/prompts/z-implement-all.md:668:     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./exports/codex/prompts/z-implement-all.md:678:     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./exports/codex/prompts/z-implement-all.md:685:     "$(printf '{"run":"%s","parent_command":"implement-all","candidates_emitted":0,"accepted":0}' "$RUN")"
./exports/codex/prompts/z-implement-all.md:708:        "$(printf '{"run":"%s","parent_command":"implement-all","subagent_model":"haiku","subagent_input_tokens":%d,"subagent_output_tokens":%d,"candidates_emitted":%d,"accepted":"<filled-in-later>"}' \
./exports/codex/prompts/z-implement-all.md:717:      Push-notify: "Memory review produced `<N>` candidate(s) — please review."
./exports/codex/prompts/z-implement-all-skill.md:586:## Phase 9 — Memory review (auto)
./exports/codex/prompts/z-implement-all-skill.md:593:   MEMORY_REVIEW_OUT="$(bash scripts/run-memory-review.sh "$RUN" "implement-all")"
./exports/codex/prompts/z-implement-all-skill.md:625:     description="Memory review for <SLUG_FOR_DESC>",
./exports/codex/prompts/z-implement-all-skill.md:632:   parent_command: implement-all"
./exports/codex/prompts/z-implement-all-skill.md:658:     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./exports/codex/prompts/z-implement-all-skill.md:668:     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./exports/codex/prompts/z-implement-all-skill.md:675:     "$(printf '{"run":"%s","parent_command":"implement-all","candidates_emitted":0,"accepted":0}' "$RUN")"
./exports/codex/prompts/z-implement-all-skill.md:698:        "$(printf '{"run":"%s","parent_command":"implement-all","subagent_model":"haiku","subagent_input_tokens":%d,"subagent_output_tokens":%d,"candidates_emitted":%d,"accepted":"<filled-in-later>"}' \
./exports/codex/prompts/z-implement-all-skill.md:707:      Push-notify: "Memory review produced `<N>` candidate(s) — please review."
./z-harness/plans/memory-self-improve-loop/SPEC.md:53:   - `parent_command:` one of `"implement-all"` or `"review-all"` (informs what kind of signals to look for)
./z-harness/plans/memory-self-improve-loop/SPEC.md:88:### `scripts/run-memory-review.sh`
./z-harness/plans/memory-self-improve-loop/SPEC.md:92:Signature: `bash scripts/run-memory-review.sh <RUN> <parent_command>`
./z-harness/plans/memory-self-improve-loop/SPEC.md:94:Where `<parent_command>` is `implement-all` or `review-all`.
./z-harness/plans/memory-self-improve-loop/SPEC.md:101:   - Parse `$BASE/TASKS.md`; count `[x]`. If zero AND parent_command is `implement-all` → skip with `skip_reason: all_tasks_skipped`, exit 0.
./z-harness/plans/memory-self-improve-loop/SPEC.md:121:- `source_file: ["agents/review-agent.md", "scripts/run-memory-review.sh"]`
./z-harness/plans/memory-self-improve-loop/SPEC.md:137:Insert a new `## Phase 9 — Memory review (auto)` section **AFTER** the existing Finalize block (which currently ends ~line 605) and **AFTER** the existing finalize push-notify, **BEFORE** the "Hard rules" / closing section.
./z-harness/plans/memory-self-improve-loop/SPEC.md:140:1. Call `bash scripts/run-memory-review.sh "$RUN" "implement-all"`. Capture stdout.
./z-harness/plans/memory-self-improve-loop/SPEC.md:147:     description="Memory review for <slug>",
./z-harness/plans/memory-self-improve-loop/SPEC.md:148:     prompt="run_dir: <RUN_DIR>\ncumulative_diff_path: <PATH>\nspec_path: <BASE>/SPEC.md\ntags_path: docs/llm/TAGS.txt\nrun_id: <RUN>\nparent_command: implement-all"
./z-harness/plans/memory-self-improve-loop/SPEC.md:166:Insert a new `## Phase 7 — Memory review (auto)` section AFTER Phase 6's `.review_state.json` cleanup (line ~368) and AFTER the existing Phase 6 push-notify, BEFORE the "Hard rules" / closing section.
./z-harness/plans/memory-self-improve-loop/SPEC.md:168:Body identical to /z-implement-all Phase 9 above EXCEPT `parent_command: review-all` in the Agent dispatch, and the SPEC.md path passed to the agent should be `$BASE/SPEC.md` (which exists since /z-review-all is post-/z-plan).
./z-harness/plans/memory-self-improve-loop/SPEC.md:180:Output line per call: `<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input/output>`.
./z-harness/plans/memory-self-improve-loop/SPEC.md:201:- **Tags-file collision.** If `docs/llm/TAGS.txt` is missing entirely (e.g. fresh repo), `run-memory-review.sh` soft-skips with `skip_reason: tags_missing`. Orchestrator does NOT auto-create TAGS.txt — that's `/z-suggest-memory`'s Phase 0 responsibility.
./z-harness/plans/memory-self-improve-loop/SPEC.md:208:- **DRY:** Both /z-implement-all and /z-review-all share `scripts/run-memory-review.sh` for skip-conditions + path resolution. They share the same agent contract. Only the new phase's body and dispatch live in the two command files (minimal duplication; the orchestration loop is identical).
./z-harness/plans/memory-self-improve-loop/PLAN.md:44:1. **Agent file + helper script** — create `agents/review-agent.md` and `scripts/run-memory-review.sh`. No callers yet; both are inert.
./z-harness/plans/memory-self-improve-loop/PLAN.md:54:- **DRY**: `scripts/run-memory-review.sh` factors out skip-conditions + path resolution so both command files just call the helper. Schema aligned with `/z-suggest-memory` so no translation layer.
./z-harness/plans/memory-self-improve-loop/TASKS.md:75:## T004 — Author `scripts/run-memory-review.sh`
./z-harness/plans/memory-self-improve-loop/TASKS.md:77:**Files touched:** `scripts/run-memory-review.sh` (NEW).
./z-harness/plans/memory-self-improve-loop/TASKS.md:81:**Description:** Implement the shell helper per SPEC.md "scripts/run-memory-review.sh" section. Skip-conditions check (empty diff, all_tasks_skipped — NOT halted-early), cumulative diff capture (truncate to 5000 lines), TAGS.txt presence check, STATUS line output, exit 0 on all paths.
./z-harness/plans/memory-self-improve-loop/TASKS.md:84:- `bash scripts/run-memory-review.sh <RUN> implement-all` prints `STATUS: ready` and three absolute paths when conditions are met.
./z-harness/plans/memory-self-improve-loop/TASKS.md:103:**Description:** Insert a new `## Phase 9 — Memory review (auto)` section after the existing Finalize block (after the existing primary-deliverable push-notify) and before "Hard rules". Body follows SPEC.md /z-implement-all section exactly: helper invocation, STATUS parse, Agent dispatch with full prompt, JSON parse with fenced-block extraction, malformed-output soft-skip, empty-candidates quiet exit, candidate persistence to `$RUN_DIR/memory-candidates.jsonl`, `review_agent_call` event emit, sequential AskUserQuestion per candidate (max 3 candidates × 4 options: Accept / Edit / Skip-with-reason / Skip-all-remaining), per-Accept `/z-suggest-memory` dispatch, final `phase_end` accounting.
./z-harness/plans/memory-self-improve-loop/TASKS.md:123:**Description:** Insert a new `## Phase 7 — Memory review (auto)` section after Phase 6's `.review_state.json` cleanup and after the existing Phase 6 push-notify, before Hard rules. Body identical to T005 EXCEPT `parent_command: review-all` in the Agent dispatch and `spec_path: $BASE/SPEC.md` (which exists post-/z-plan).
./z-harness/plans/memory-self-improve-loop/TASKS.md:128:- Differs only in `parent_command` literal and any /z-review-all-specific phrasing.
./z-harness/plans/memory-self-improve-loop/TASKS.md:164:Output format: `<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input>/<output>`.
./z-harness/plans/tiered-quality-uplift/archive/tasks/T009/diff-tracked.patch:440:+- `parent_command:` one of `"implement-all"` or `"review-all"` (informs what kind of signals to look for)
./z-harness/plans/tiered-quality-uplift/archive/tasks/T009/diff-v1.patch:441:+- `parent_command:` one of `"implement-all"` or `"review-all"` (informs what kind of signals to look for)
./z-harness/plans/memory-self-improve-loop/archive/20260525T211925Z-memory-self-improve-loop/transcripts/001-codex-research-review.response.md:3:- Hermes has more memory surfaces than `SessionDB + FTS5`: built-in `MEMORY.md` / `USER.md`, optional external memory providers, and the background memory review nudge. The draft maps session search well, but treats it as the long-term memory stack rather than one recall layer.
./z-harness/plans/memory-self-improve-loop/archive/20260525T211925Z-memory-self-improve-loop/transcripts/001-codex-research-review.response.md:17:- “The actual self-improvement loop” as only Skill Documents is mislabeled. Hermes’s actual self-improvement loop includes both memory review and skill review, sometimes combined in one background fork.
./z-harness/plans/memory-self-improve-loop/archive/20260525T211925Z-memory-self-improve-loop/transcripts/001-codex-research-review.response.md:35:- Hermes has more memory surfaces than `SessionDB + FTS5`: built-in `MEMORY.md` / `USER.md`, optional external memory providers, and the background memory review nudge. The draft maps session search well, but treats it as the long-term memory stack rather than one recall layer.
./z-harness/plans/memory-self-improve-loop/archive/20260525T211925Z-memory-self-improve-loop/transcripts/001-codex-research-review.response.md:49:- “The actual self-improvement loop” as only Skill Documents is mislabeled. Hermes’s actual self-improvement loop includes both memory review and skill review, sometimes combined in one background fork.
./z-harness/plans/tiered-quality-uplift/archive/tasks/T009/diff.patch:441:+- `parent_command:` one of `"implement-all"` or `"review-all"` (informs what kind of signals to look for)
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/findings.md:57:- **[codex]** SPEC's `all_tasks_skipped` skip-condition is ambiguously named: the implementation in `scripts/run-memory-review.sh:72-85` checks for "zero `[x]` in TASKS.md" which equally matches "no tasks executed yet" — not literally "all tasks were user-skipped." Rename or add a sentence of clarification.
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.stat:14:     111 scripts/run-memory-review.sh
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:128:+## Phase 9 — Memory review (auto)
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:135:+   MEMORY_REVIEW_OUT="$(bash scripts/run-memory-review.sh "$RUN" "implement-all")"
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:167:+     description="Memory review for <SLUG_FOR_DESC>",
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:174:+   parent_command: implement-all"
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:200:+     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:210:+     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:217:+     "$(printf '{"run":"%s","parent_command":"implement-all","candidates_emitted":0,"accepted":0}' "$RUN")"
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:240:+        "$(printf '{"run":"%s","parent_command":"implement-all","subagent_model":"haiku","subagent_input_tokens":%d,"subagent_output_tokens":%d,"candidates_emitted":%d,"accepted":"<filled-in-later>"}' \
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:249:+      Push-notify: "Memory review produced `<N>` candidate(s) — please review."
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:564:+## Phase 7 — Memory review (auto)
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:566:+1. Call `bash scripts/run-memory-review.sh "$RRUN" "review-all"`. Capture stdout.
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:581:+     description="Memory review for <slug>",
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:582:+     prompt="run_dir: <RUN_DIR>\ncumulative_diff_path: <cumulative.diff path>\nspec_path: $BASE/SPEC.md\ntags_path: docs/llm/TAGS.txt\nindex_path: docs/llm/INDEX.json\nrun_id: <RRUN>\nparent_command: review-all"
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:589:+   # Push-notify: "Memory review output was malformed — no valid fenced json block found. Check events.jsonl for review_agent_malformed."
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:665:+Output format per line: `<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input>/<output>`
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:883:+        "scripts/run-memory-review.sh"
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:895:+      "summary": "Post-run Haiku subagent that proposes 0-3 candidate memories from a completed /z-implement-all or /z-review-all run. Reads run events, cumulative diff, and SPEC.md; emits structured candidates as a fenced JSON block. Does not write — orchestrator owns all writes via /z-suggest-memory. Dispatched by scripts/run-memory-review.sh after skip-conditions check (empty diff, zero tasks completed)."
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1091:+## Phase 9 — Memory review (auto)
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1098:+   MEMORY_REVIEW_OUT="$(bash scripts/run-memory-review.sh "$RUN" "implement-all")"
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1130:+     description="Memory review for <SLUG_FOR_DESC>",
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1137:+   parent_command: implement-all"
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1163:+     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1173:+     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1180:+     "$(printf '{"run":"%s","parent_command":"implement-all","candidates_emitted":0,"accepted":0}' "$RUN")"
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1203:+        "$(printf '{"run":"%s","parent_command":"implement-all","subagent_model":"haiku","subagent_input_tokens":%d,"subagent_output_tokens":%d,"candidates_emitted":%d,"accepted":"<filled-in-later>"}' \
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1212:+      Push-notify: "Memory review produced `<N>` candidate(s) — please review."
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1511:+## Phase 7 — Memory review (auto)
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1513:+1. Call `bash scripts/run-memory-review.sh "$RRUN" "review-all"`. Capture stdout.
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1528:+     description="Memory review for <slug>",
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1529:+     prompt="run_dir: <RUN_DIR>\ncumulative_diff_path: <cumulative.diff path>\nspec_path: $BASE/SPEC.md\ntags_path: docs/llm/TAGS.txt\nindex_path: docs/llm/INDEX.json\nrun_id: <RRUN>\nparent_command: review-all"
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1536:+   # Push-notify: "Memory review output was malformed — no valid fenced json block found. Check events.jsonl for review_agent_malformed."
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1612:+Output format per line: `<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input>/<output>`
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1739:+- `parent_command:` one of `"implement-all"` or `"review-all"` (informs what kind of signals to look for)
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1797:diff --git a/scripts/run-memory-review.sh b/scripts/run-memory-review.sh
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1801:+++ b/scripts/run-memory-review.sh
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1807:+# Usage: bash scripts/run-memory-review.sh <RUN> <parent_command>
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1808:+#   parent_command: implement-all | review-all
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1822:+PARENT_COMMAND="$2"
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1875:+if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1923:+> Covers source: agents/review-agent.md, scripts/run-memory-review.sh
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1938:+Before dispatching the agent, `scripts/run-memory-review.sh` performs a skip-conditions check:
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:1998:+<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input/output>
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:2018:+There is no per-call wall-clock timeout in the current `Agent(...)` infrastructure. If the Haiku subagent call hangs, **ctrl-c is the only escape**. The parent command's primary-deliverable push-notify has already fired at this point, so ctrl-c aborts only the memory review phase, not the run's main output.
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:2049:+    "scripts/run-memory-review.sh"
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/cumulative.diff:2069:+    "run-memory-review.sh soft-skips (exit 0) on missing TAGS.txt rather than failing hard",
./z-harness/plans/memory-self-improve-loop/archive/20260526T002218Z-review/REVIEW-TASKS.md:86:- **Acceptance:** run `/z-amend "Rename all_tasks_skipped to no_tasks_completed (or add a one-sentence clarification) so the skip-reason name matches what scripts/run-memory-review.sh actually detects (zero [x] in TASKS.md, regardless of whether the run is fresh or user-skipped). Update scripts/run-memory-review.sh STATUS string to match."`; SPEC + script aligned.
./z-harness/plans/tiered-quality-uplift/archive/tasks/T008/diff-tracked.patch:176:       "summary": "Post-run Haiku subagent that proposes 0-3 candidate memories from a completed /z-implement-all or /z-review-all run. Reads run events, cumulative diff, and SPEC.md; emits structured candidates as a fenced JSON block. Does not write \u2014 orchestrator owns all writes via /z-suggest-memory. Dispatched by scripts/run-memory-review.sh after skip-conditions check (empty diff, zero tasks completed)."
./z-harness/plans/tiered-quality-uplift/archive/tasks/T008/diff-v1.patch:337:       "summary": "Post-run Haiku subagent that proposes 0-3 candidate memories from a completed /z-implement-all or /z-review-all run. Reads run events, cumulative diff, and SPEC.md; emits structured candidates as a fenced JSON block. Does not write \u2014 orchestrator owns all writes via /z-suggest-memory. Dispatched by scripts/run-memory-review.sh after skip-conditions check (empty diff, zero tasks completed)."
./z-harness/plans/tiered-quality-uplift/archive/tasks/T008/review.response.md:530:      "summary": "Post-run Haiku subagent that proposes 0-3 candidate memories from a completed /z-implement-all or /z-review-all run. Reads run events, cumulative diff, and SPEC.md; emits structured candidates as a fenced JSON block. Does not write \u2014 orchestrator owns all writes via /z-suggest-memory. Dispatched by scripts/run-memory-review.sh after skip-conditions check (empty diff, zero tasks completed)."
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/decisions.md:85:  - (b) Soft-skip: log `review_agent_failed` event, push-notify with "memory review skipped due to <reason>", proceed to finalize normally
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/decisions.md:87:- **Tentative call:** (b). The parent command's primary deliverable (TASKS.md status, REVIEW-TASKS.md) is already complete by the time the review-agent fires — a failed memory review must not block the user from seeing that result. v1 deliberately ships without retry to keep the cost story simple ("at most one Haiku call per major command").
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/SPEC.md:48:   - `parent_command:` one of `"implement-all"` or `"review-all"` (informs what kind of signals to look for)
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/SPEC.md:83:### `scripts/run-memory-review.sh`
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/SPEC.md:87:Signature: `bash scripts/run-memory-review.sh <RUN> <parent_command>`
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/SPEC.md:89:Where `<parent_command>` is `implement-all` or `review-all`.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/SPEC.md:96:   - Parse `$BASE/TASKS.md`; count `[x]`. If zero AND parent_command is `implement-all` → skip with `skip_reason: all_tasks_skipped`, exit 0.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/SPEC.md:116:- `source_file: ["agents/review-agent.md", "scripts/run-memory-review.sh"]`
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/SPEC.md:132:Insert a new `## Phase 9 — Memory review (auto)` section **AFTER** the existing Finalize block (which currently ends ~line 605) and **AFTER** the existing finalize push-notify, **BEFORE** the "Hard rules" / closing section.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/SPEC.md:135:1. Call `bash scripts/run-memory-review.sh "$RUN" "implement-all"`. Capture stdout.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/SPEC.md:142:     description="Memory review for <slug>",
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/SPEC.md:143:     prompt="run_dir: <RUN_DIR>\ncumulative_diff_path: <PATH>\nspec_path: <BASE>/SPEC.md\ntags_path: docs/llm/TAGS.txt\nrun_id: <RUN>\nparent_command: implement-all"
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/SPEC.md:161:Insert a new `## Phase 7 — Memory review (auto)` section AFTER Phase 6's `.review_state.json` cleanup (line ~368) and AFTER the existing Phase 6 push-notify, BEFORE the "Hard rules" / closing section.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/SPEC.md:163:Body identical to /z-implement-all Phase 9 above EXCEPT `parent_command: review-all` in the Agent dispatch, and the SPEC.md path passed to the agent should be `$BASE/SPEC.md` (which exists since /z-review-all is post-/z-plan).
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/SPEC.md:175:Output line per call: `<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input/output>`.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/SPEC.md:196:- **Tags-file collision.** If `docs/llm/TAGS.txt` is missing entirely (e.g. fresh repo), `run-memory-review.sh` soft-skips with `skip_reason: tags_missing`. Orchestrator does NOT auto-create TAGS.txt — that's `/z-suggest-memory`'s Phase 0 responsibility.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/SPEC.md:203:- **DRY:** Both /z-implement-all and /z-review-all share `scripts/run-memory-review.sh` for skip-conditions + path resolution. They share the same agent contract. Only the new phase's body and dispatch live in the two command files (minimal duplication; the orchestration loop is identical).
./z-harness/plans/tiered-quality-uplift/archive/tasks/T008/diff.patch:337:       "summary": "Post-run Haiku subagent that proposes 0-3 candidate memories from a completed /z-implement-all or /z-review-all run. Reads run events, cumulative diff, and SPEC.md; emits structured candidates as a fenced JSON block. Does not write \u2014 orchestrator owns all writes via /z-suggest-memory. Dispatched by scripts/run-memory-review.sh after skip-conditions check (empty diff, zero tasks completed)."
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/PLAN.md:44:1. **Agent file + helper script** — create `agents/review-agent.md` and `scripts/run-memory-review.sh`. No callers yet; both are inert.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/PLAN.md:54:- **DRY**: `scripts/run-memory-review.sh` factors out skip-conditions + path resolution so both command files just call the helper. Schema aligned with `/z-suggest-memory` so no translation layer.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff-v1.patch:244:+## Phase 7 — Memory review (auto)
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff-v1.patch:246:+1. Call `bash scripts/run-memory-review.sh "$RRUN" "review-all"`. Capture stdout.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff-v1.patch:261:+     description="Memory review for <slug>",
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff-v1.patch:262:+     prompt="run_dir: <RUN_DIR>\ncumulative_diff_path: <cumulative.diff path>\nspec_path: $BASE/SPEC.md\ntags_path: docs/llm/TAGS.txt\nrun_id: <RRUN>\nparent_command: review-all"
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff-v1.patch:269:+   # Push-notify: "Memory review output was malformed — no valid fenced json block found. Check events.jsonl for review_agent_malformed."
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff.patch:244:+## Phase 7 — Memory review (auto)
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff.patch:246:+1. Call `bash scripts/run-memory-review.sh "$RRUN" "review-all"`. Capture stdout.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff.patch:261:+     description="Memory review for <slug>",
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff.patch:262:+     prompt="run_dir: <RUN_DIR>\ncumulative_diff_path: <cumulative.diff path>\nspec_path: $BASE/SPEC.md\ntags_path: docs/llm/TAGS.txt\nrun_id: <RRUN>\nparent_command: review-all"
./z-harness/plans/memory-self-improve-loop/archive/tasks/T006/diff.patch:269:+   # Push-notify: "Memory review output was malformed — no valid fenced json block found. Check events.jsonl for review_agent_malformed."
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/TASKS.md:75:## T004 — Author `scripts/run-memory-review.sh`
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/TASKS.md:77:**Files touched:** `scripts/run-memory-review.sh` (NEW).
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/TASKS.md:81:**Description:** Implement the shell helper per SPEC.md "scripts/run-memory-review.sh" section. Skip-conditions check (empty diff, all_tasks_skipped — NOT halted-early), cumulative diff capture (truncate to 5000 lines), TAGS.txt presence check, STATUS line output, exit 0 on all paths.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/TASKS.md:84:- `bash scripts/run-memory-review.sh <RUN> implement-all` prints `STATUS: ready` and three absolute paths when conditions are met.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/TASKS.md:103:**Description:** Insert a new `## Phase 9 — Memory review (auto)` section after the existing Finalize block (after the existing primary-deliverable push-notify) and before "Hard rules". Body follows SPEC.md /z-implement-all section exactly: helper invocation, STATUS parse, Agent dispatch with full prompt, JSON parse with fenced-block extraction, malformed-output soft-skip, empty-candidates quiet exit, candidate persistence to `$RUN_DIR/memory-candidates.jsonl`, `review_agent_call` event emit, sequential AskUserQuestion per candidate (max 3 candidates × 4 options: Accept / Edit / Skip-with-reason / Skip-all-remaining), per-Accept `/z-suggest-memory` dispatch, final `phase_end` accounting.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/TASKS.md:123:**Description:** Insert a new `## Phase 7 — Memory review (auto)` section after Phase 6's `.review_state.json` cleanup and after the existing Phase 6 push-notify, before Hard rules. Body identical to T005 EXCEPT `parent_command: review-all` in the Agent dispatch and `spec_path: $BASE/SPEC.md` (which exists post-/z-plan).
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/TASKS.md:128:- Differs only in `parent_command` literal and any /z-review-all-specific phrasing.
./z-harness/plans/memory-self-improve-loop/archive/20260525T214818Z-memory-self-improve-loop/TASKS.md:164:Output format: `<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input>/<output>`.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T001/diff.patch:59:+   - `parent_command:` one of `"implement-all"` or `"review-all"` (informs what kind of signals to look for)
./z-harness/plans/memory-self-improve-loop/archive/tasks/T001/diff.patch:94:+### `scripts/run-memory-review.sh`
./z-harness/plans/memory-self-improve-loop/archive/tasks/T001/diff.patch:98:+Signature: `bash scripts/run-memory-review.sh <RUN> <parent_command>`
./z-harness/plans/memory-self-improve-loop/archive/tasks/T001/diff.patch:100:+Where `<parent_command>` is `implement-all` or `review-all`.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T001/diff.patch:107:+   - Parse `$BASE/TASKS.md`; count `[x]`. If zero AND parent_command is `implement-all` → skip with `skip_reason: all_tasks_skipped`, exit 0.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T001/diff.patch:127:+- `source_file: ["agents/review-agent.md", "scripts/run-memory-review.sh"]`
./z-harness/plans/memory-self-improve-loop/archive/tasks/T001/diff.patch:143:+Insert a new `## Phase 9 — Memory review (auto)` section **AFTER** the existing Finalize block (which currently ends ~line 605) and **AFTER** the existing finalize push-notify, **BEFORE** the "Hard rules" / closing section.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T001/diff.patch:146:+1. Call `bash scripts/run-memory-review.sh "$RUN" "implement-all"`. Capture stdout.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T001/diff.patch:153:+     description="Memory review for <slug>",
./z-harness/plans/memory-self-improve-loop/archive/tasks/T001/diff.patch:154:+     prompt="run_dir: <RUN_DIR>\ncumulative_diff_path: <PATH>\nspec_path: <BASE>/SPEC.md\ntags_path: docs/llm/TAGS.txt\nrun_id: <RUN>\nparent_command: implement-all"
./z-harness/plans/memory-self-improve-loop/archive/tasks/T001/diff.patch:172:+Insert a new `## Phase 7 — Memory review (auto)` section AFTER Phase 6's `.review_state.json` cleanup (line ~368) and AFTER the existing Phase 6 push-notify, BEFORE the "Hard rules" / closing section.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T001/diff.patch:174:+Body identical to /z-implement-all Phase 9 above EXCEPT `parent_command: review-all` in the Agent dispatch, and the SPEC.md path passed to the agent should be `$BASE/SPEC.md` (which exists since /z-review-all is post-/z-plan).
./z-harness/plans/memory-self-improve-loop/archive/tasks/T001/diff.patch:186:+Output line per call: `<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input/output>`.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T001/diff.patch:207:+- **Tags-file collision.** If `docs/llm/TAGS.txt` is missing entirely (e.g. fresh repo), `run-memory-review.sh` soft-skips with `skip_reason: tags_missing`. Orchestrator does NOT auto-create TAGS.txt — that's `/z-suggest-memory`'s Phase 0 responsibility.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T001/diff.patch:214:+- **DRY:** Both /z-implement-all and /z-review-all share `scripts/run-memory-review.sh` for skip-conditions + path resolution. They share the same agent contract. Only the new phase's body and dispatch live in the two command files (minimal duplication; the orchestration loop is identical).
./z-harness/plans/memory-self-improve-loop/archive/tasks/T004/diff-v1.patch:1:diff --git a/Users/zeke/dev/z-harness/scripts/run-memory-review.sh b/Users/zeke/dev/z-harness/scripts/run-memory-review.sh
./z-harness/plans/memory-self-improve-loop/archive/tasks/T004/diff-v1.patch:5:+++ b/Users/zeke/dev/z-harness/scripts/run-memory-review.sh
./z-harness/plans/memory-self-improve-loop/archive/tasks/T004/diff-v1.patch:11:+# Usage: bash scripts/run-memory-review.sh <RUN> <parent_command>
./z-harness/plans/memory-self-improve-loop/archive/tasks/T004/diff-v1.patch:12:+#   parent_command: implement-all | review-all
./z-harness/plans/memory-self-improve-loop/archive/tasks/T004/diff-v1.patch:21:+  echo "usage: run-memory-review.sh <RUN> <parent_command>" >&2
./z-harness/plans/memory-self-improve-loop/archive/tasks/T004/diff-v1.patch:26:+PARENT_COMMAND="$2"
./z-harness/plans/memory-self-improve-loop/archive/tasks/T004/diff-v1.patch:35:+  echo "run-memory-review.sh: Z_HARNESS_PLAN_DIR is not set" >&2
./z-harness/plans/memory-self-improve-loop/archive/tasks/T004/diff-v1.patch:57:+if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
./z-harness/plans/memory-self-improve-loop/archive/tasks/T004/diff.patch:1:diff --git a/Users/zeke/dev/z-harness/scripts/run-memory-review.sh b/Users/zeke/dev/z-harness/scripts/run-memory-review.sh
./z-harness/plans/memory-self-improve-loop/archive/tasks/T004/diff.patch:5:+++ b/Users/zeke/dev/z-harness/scripts/run-memory-review.sh
./z-harness/plans/memory-self-improve-loop/archive/tasks/T004/diff.patch:11:+# Usage: bash scripts/run-memory-review.sh <RUN> <parent_command>
./z-harness/plans/memory-self-improve-loop/archive/tasks/T004/diff.patch:12:+#   parent_command: implement-all | review-all
./z-harness/plans/memory-self-improve-loop/archive/tasks/T004/diff.patch:21:+  echo "usage: run-memory-review.sh <RUN> <parent_command>" >&2
./z-harness/plans/memory-self-improve-loop/archive/tasks/T004/diff.patch:26:+PARENT_COMMAND="$2"
./z-harness/plans/memory-self-improve-loop/archive/tasks/T004/diff.patch:35:+  echo "run-memory-review.sh: Z_HARNESS_PLAN_DIR is not set" >&2
./z-harness/plans/memory-self-improve-loop/archive/tasks/T004/diff.patch:57:+if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
./z-harness/plans/memory-self-improve-loop/archive/tasks/T003/diff-v1.patch:27:+- `parent_command:` one of `"implement-all"` or `"review-all"` (informs what kind of signals to look for)
./z-harness/plans/memory-self-improve-loop/archive/tasks/T003/diff.patch:27:+- `parent_command:` one of `"implement-all"` or `"review-all"` (informs what kind of signals to look for)
./z-harness/plans/memory-self-improve-loop/REVIEW-TASKS.md:86:- **Acceptance:** run `/z-amend "Rename all_tasks_skipped to no_tasks_completed (or add a one-sentence clarification) so the skip-reason name matches what scripts/run-memory-review.sh actually detects (zero [x] in TASKS.md, regardless of whether the run is fresh or user-skipped). Update scripts/run-memory-review.sh STATUS string to match."`; SPEC + script aligned.
./z-harness/plans/memory-self-improve-loop/archive/tasks/T005/diff.patch:128:+## Phase 9 — Memory review (auto)
./z-harness/plans/memory-self-improve-loop/archive/tasks/T005/diff.patch:135:+   MEMORY_REVIEW_OUT="$(bash scripts/run-memory-review.sh "$RUN" "implement-all")"
./z-harness/plans/memory-self-improve-loop/archive/tasks/T005/diff.patch:167:+     description="Memory review for <SLUG_FOR_DESC>",
./z-harness/plans/memory-self-improve-loop/archive/tasks/T005/diff.patch:174:+   parent_command: implement-all"
./z-harness/plans/memory-self-improve-loop/archive/tasks/T005/diff.patch:200:+     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./z-harness/plans/memory-self-improve-loop/archive/tasks/T005/diff.patch:210:+     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
./z-harness/plans/memory-self-improve-loop/archive/tasks/T005/diff.patch:217:+     "$(printf '{"run":"%s","parent_command":"implement-all","candidates_emitted":0,"accepted":0}' "$RUN")"
./z-harness/plans/memory-self-improve-loop/archive/tasks/T005/diff.patch:240:+        "$(printf '{"run":"%s","parent_command":"implement-all","subagent_model":"haiku","subagent_input_tokens":%d,"subagent_output_tokens":%d,"candidates_emitted":%d,"accepted":"<filled-in-later>"}' \
./z-harness/plans/memory-self-improve-loop/archive/tasks/T005/diff.patch:249:+      Push-notify: "Memory review produced `<N>` candidate(s) — please review."

codex
No blockers or majors found.
tokens used
52,234
No blockers or majors found.
