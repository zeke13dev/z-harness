You are reviewing code that Claude just wrote for task subagent-liveness (RETRY v5 — addresses both v4 blockers): a post-hoc liveness inspector for detecting hung subagents during /z-plan and /z-implement-all runs.

Acceptance criteria (verbatim from FIX.md):
- [ ] `scripts/liveness.sh` runs against an existing `events.jsonl` and reports any `*_start` with no `*_end` plus elapsed seconds; exits 0 (no stuck) or 1 (stuck found).
- [ ] `scripts/check-timeout.sh` when sourced sets `TIMEOUT_CMD` (empty if neither `timeout` nor `gtimeout` available) and emits exactly one `timeout_availability` event per run.
- [ ] Each of the three agent files calls `check-timeout.sh` instead of detecting inline; the `TIMEOUT_CMD` variable is still referenced by the subsequent CLI-call block (no behavior change to provider invocation).
- [ ] `docs/human/LIVENESS.md` documents the inspector with one usage example.
- [ ] No regression: a normal `/z-plan` or `/z-implement-next` run still works (verified by syntax-checking the scripts and reviewing the agent diffs — no e2e test in light mode).

v4 blockers being fixed in v5:
1. BLOCKER (v4): match_key() returns 3-tuple but the row-construction loop unpacked 2-tuple → ValueError on any unclosed start.
   FIX: liveness.sh row loop now unpacks the full key (base, tid, _retry, role), and the print path threads `role` through into the row tuple + output tag.

2. BLOCKER (v4): match_key() didn't include `role` → parallel consultant_primary + consultant_secondary `consult_start` events collapsed to same key, one `consult` close erased both.
   FIX: match_key() now includes `role` in the discriminator. The consult_start events emitted by the agent files already carry `role` in their payload, and the existing post-call `consult` event also has `role`, so primary/secondary now track and close independently. Output also displays the role tag for stuck consult starts.

Diff (primary artifact — focus on what changed and whether it fixes the stated blockers):

diff --git a/agents/consultant-primary.md b/agents/consultant-primary.md
index 6b4da11..652c81b 100644
--- a/agents/consultant-primary.md
+++ b/agents/consultant-primary.md
@@ -25,11 +25,21 @@ USE_STDIN="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.loa
 MODEL_LABEL="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["model_label"])')"
 TIMEOUT="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["timeout_s"])')"
 
-TIMEOUT_CMD="$(command -v timeout || command -v gtimeout || true)"
-if [ -z "$TIMEOUT_CMD" ] && [ -z "$Z_HARNESS_TIMEOUT_WARNED" ]; then
-  echo "[providers] timeout(1) not on PATH — provider timeout disabled. brew install coreutils to restore." >&2
-  export Z_HARNESS_TIMEOUT_WARNED=1
-fi
+# $RUN is the run-id the caller passed in (see "Archiving" section below).
+# Set it now — check-timeout.sh keys the per-run timeout_availability marker
+# on it, and without it the event isn't emitted.
+RUN="<run-id from caller>"
+
+# Detects timeout(1)/gtimeout, sets $TIMEOUT_CMD, and emits one
+# `timeout_availability` event per run so silent-disable is debuggable.
+source "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/check-timeout.sh" "$RUN"
+
+# Emit `consult_start` BEFORE the provider CLI call so scripts/liveness.sh
+# can detect a hung consultant even when $TIMEOUT_CMD is empty (no coreutils
+# on PATH). The existing post-call `consult` event in the Archiving section
+# below is the matching end-marker (see END_KIND_TO_BASE in liveness.sh).
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" consult_start \
+  "$(printf '{"role":"consultant_primary","mode":"%s","provider":"%s"}' "$MODE" "$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; print(json.load(sys.stdin)["provider"])')")"
 
 if [ "$USE_STDIN" = "True" ]; then
   if [ -n "$TIMEOUT_CMD" ]; then
[same changes in consultant-secondary.md and reviewer.md...]

diff --git a/scripts/liveness.sh b/scripts/liveness.sh
new file mode 100755
index 0000000..221b549
--- /dev/null
+++ b/scripts/liveness.sh
[file contents shown in full earlier...]

Key sections of liveness.sh to scrutinize:

Lines 375-383 (match_key function):
+def match_key(base, ev):
+    # Discriminators so distinct attempts/parallel calls don't close each other:
+    #   - id      → per-task identifier
+    #   - retry/cycle/attempt → distinct attempts at the same task
+    #   - role    → consultant_primary vs consultant_secondary running in parallel
+    tid = ev.get("id") or ""
+    retry = ev.get("retry", ev.get("cycle", ev.get("attempt", "")))
+    role = ev.get("role", "")
+    return (base, tid, str(retry), role)

Lines 425-433 (row construction with key unpacking):
+    for key, ev in starts.items():
+        base, tid, _retry, role = key
+        try:
+            elapsed = int(now - parse_ts(ev["ts"]))
+        except Exception:
+            elapsed = -1
+        if not show_all and (elapsed < stale_seconds or elapsed < 0):
+            continue
+        rows.append((base, tid, role, elapsed, ev))

Lines 448-454 (output with role tag):
+    for base, tid, role, elapsed, ev in sorted(rows, key=lambda r: -r[3]):
+        tag = ""
+        if tid:
+            tag += f" [{tid}]"
+        if role:
+            tag += f" ({role})"
+        print(f"    - {base}_start{tag}: {elapsed}s ago  (ts={ev['ts']})")

Scrutinize this code rigorously. Claude is prone to over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope beyond the spec.

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
- Report blockers and majors only. Skip minors and nits unless a "minor" hides a correctness bug.
- One finding per bullet. Two sentences max per finding.
- No re-stating of code already in the diff. No summaries of what the code does. No restating the spec.
- If there are no blockers or majors, respond with exactly: `No blockers or majors found.` (plus an optional 1-line note if something needs the implementer's attention but is below the bar).
