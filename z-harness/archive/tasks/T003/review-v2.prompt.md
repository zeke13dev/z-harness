You are reviewing code that Claude just wrote for task T003: Implement Phase 2 (cross-cutting pass): consultant dispatch + 3-tier classification.

This is ROUND v2 review. The implementer claims these 8 v1 majors were fixed:
- M1. --cross-cutting=skip control flow not enforced (no else/guard).
- M2. Merge/classification step underspecified (prose only).
- M3. Entry-file fallback root dir silently dropped.
- M4. First non-test source heuristic too broad (LICENSE/NOTICE).
- M5. G_COUNT computed after the if-check that gates on it.
- M6. TASKS.md finding parser mishandled field order.
- M7. MANIFEST insertion not idempotent.
- M8. grep -c || echo 0 telemetry bug.

Spec (excerpt, lines 97-116 from SPEC.md):
```
### Cross-cutting pass (`commands/z-uplift.md` Phase 2)
Dispatch shape (bare agent names — providers are resolved at dispatch by `scripts/resolve-provider.sh`, NOT hardcoded to Gemini/Codex):
```
Agent(subagent_type="consultant-primary", description="Cross-cutting (primary) for <slug>",
      prompt="MODE: cross-cutting-uplift\nrepo_root: <abs>\ncomponents: <COMPONENTS.md verbatim>\nsource_map: <top-50 files by churn over last 90 days, plus each component's entry file (heuristic below)>\nAsk: list cross-component issues (duplicated abstractions, style drift, dead code at module boundaries, public-API drift). For each, emit an explicit `component: <slug-from-MANIFEST>` marker, then classify as global-task | per-component-context | risk.")
Agent(subagent_type="consultant-secondary", description="Cross-cutting (secondary) for <slug>", prompt="<same body>")
```

**Entry-file heuristic per component** (used in `source_map` above): pick the first match, in this order: `README.md` in component root → `src/lib.rs` → `src/main.rs` → `__init__.py` → `package.json` → first non-test source file by lexicographic order → component root path itself (if no source file detected).

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
```

Acceptance criteria:
- dispatch shape matches /z-audit Phase 4
- CROSS-CUTTING.md has 3 sections with component: markers
- synthetic dir only when global-task > 0
- --cross-cutting=skip short-circuits

Delta (v2 patch showing changes since v1):
```
--- z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff-v1.patch	2026-05-25 21:19:41
+++ z-harness/plans/tiered-quality-uplift/archive/tasks/T003/diff.patch	2026-05-25 21:23:49
@@ -714,7 +714,9 @@
   "$(printf '{"phase":2,"name":"cross-cutting","wall_ms":%d,"user_wait_ms":0,"skipped":true}' "$WALL_MS")"
 ```
 
-Then skip to Phase 3.
+**STOP — do not execute Steps 1-7 below if `CROSS_CUTTING_SKIP=true`. Steps 1-7 apply only when `CROSS_CUTTING_SKIP=false`.**
+
+Otherwise (`CROSS_CUTTING_SKIP=false`), execute Steps 1-7 below:
 
 ### Step 1 — Build source map
 
@@ -763,24 +765,46 @@
     for c in candidates:
         if os.path.isfile(c):
             return os.path.relpath(c, repo_root)
-    # first non-test source file lexicographically
-    try:
-        for fname in sorted(os.listdir(abs_comp)):
-            if fname.startswith("test") or fname.startswith("_test") or fname.endswith("_test.py"):
+    # first non-test source file lexicographically (up to 2 levels deep, source extensions only)
+    SOURCE_EXTS = {
+        ".py", ".rs", ".go", ".ts", ".tsx", ".js", ".jsx",
+        ".java", ".kt", ".swift", ".cpp", ".c", ".h", ".hpp", ".rb",
+    }
+    try:
+        candidates_src = []
+        for depth, (dirpath, dirnames, filenames) in enumerate(os.walk(abs_comp)):
+            # Limit recursion to 2 levels deep
+            rel_depth = dirpath[len(abs_comp):].count(os.sep)
+            if rel_depth >= 2:
+                dirnames.clear()
                 continue
-            full = os.path.join(abs_comp, fname)
-            if os.path.isfile(full):
-                return os.path.relpath(full, repo_root)
+            # Exclude test dirs and pycache in-place so os.walk doesn't descend
+            dirnames[:] = [
+                d for d in sorted(dirnames)
+                if "test" not in d.lower() and d != "__pycache__"
+            ]
+            for fname in sorted(filenames):
+                if "test" in fname.lower():
+                    continue
+                _, ext = os.path.splitext(fname)
+                if ext not in SOURCE_EXTS:
+                    continue
+                full = os.path.join(dirpath, fname)
+                candidates_src.append(full)
+        if candidates_src:
+            return os.path.relpath(candidates_src[0], repo_root)
         except OSError:
             pass
-    # fall back to component root path itself
+    # final fallback: component root path itself (directory)
     return comp_path
 
 entry_paths = []
 for c in components:
     ep = entry_file(c["path"], repo_root)
-    if ep and os.path.isfile(os.path.join(repo_root, ep)):
-        entry_paths.append(ep)
+    if ep:
+        abs_ep = os.path.join(repo_root, ep)
+        if os.path.isfile(abs_ep) or os.path.isdir(abs_ep):
+            entry_paths.append(ep)
 
 # merge, de-duplicate, cap at ~100
 seen = set()
@@ -859,34 +883,193 @@
 
 ### Step 5 — Merge findings into CROSS-CUTTING.md
 
-Merge both consultant returns. For any finding missing a classification, default it to `per-component-context`.
+Run the following deterministic merge script. It reads both consultant transcripts, extracts each finding by its `component:` marker, normalizes into the three sections, defaults missing `class:` to `per-component-context`, and drops any finding without a `component:` marker (with a warning):
 
-Write `$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md`:
+```bash
+python3 - \
+  "$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts/phase2-consultant-primary.md" \
+  "$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts/phase2-consultant-secondary.md" \
+  "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" \
+  "$SLUG" <<'PYEOF'
+import re, sys
 
-```markdown
-# Cross-cutting findings — <slug>
+primary_path   = sys.argv[1]
+secondary_path = sys.argv[2]
+out_path       = sys.argv[3]
+slug           = sys.argv[4]
 
-## Global tasks (need dedicated plan)
-- G-001 — [HIGH] <subject> — component: <slug> — files: a, b, c
-...
+def read_safe(path):
+    try:
+        with open(path) as fh:
+            return fh.read()
+    except OSError:
+        return ""
 
-## Per-component context (inform audits)
-- C-001 — component: <slug> — <context>
-...
+def extract_findings(text):
+    """
+    Parse consultant transcript into a list of finding dicts.
+    Each finding block is delimited by lines starting with a numbered prefix
+    (G-NNN, C-NNN, R-NNN) or a markdown bullet. Fields recognised:
+      component: <slug>
+      class: global-task | per-component-context | risk
+      files: <comma-separated list>
+      subject: <free text>
+    The finding text up to the next delimiter becomes the body.
+    """
+    findings = []
+    # Split on bullet lines that start a finding number
+    blocks = re.split(r'(?=^[-*]\s+(?:G|C|R)-\d+)', text, flags=re.MULTILINE)
+    for block in blocks:
+        block = block.strip()
+        if not block:
+            continue
+        # Detect finding type from prefix
+        type_match = re.match(r'^[-*]\s+(G|C|R)-(\d+)', block)
+        if not type_match:
+            continue
+        prefix   = type_match.group(1)  # G / C / R
+        num_str  = type_match.group(2)
 
-## Risks (watch items)
-- R-001 — component: <slug> — <subject> — <evidence>
-...
+        # Parse key: value fields
+        fields = {}
+        for key in ("component", "class", "files", "subject"):
+            m = re.search(rf'(?:^|\s){re.escape(key)}:\s*(.+?)(?:\n|$)', block, re.IGNORECASE | re.MULTILINE)
+            if m:
+                fields[key] = m.group(1).strip()
+
+        # Default class from prefix if not explicitly set
+        if "class" not in fields:
+            if prefix == "G":
+                fields["class"] = "global-task"
+            elif prefix == "R":
+                fields["class"] = "risk"
+            else:
+                fields["class"] = "per-component-context"
+
+        # Drop findings missing component: marker (warn to stderr)
+        if "component" not in fields:
+            print(f"WARNING: finding {prefix}-{num_str} has no component: marker — dropped", file=sys.stderr)
+            continue
+
+        # Build subject from first non-field line if not explicitly set
+        if "subject" not in fields:
+            first_line = block.splitlines()[0] if block.splitlines() else ""
+            # Strip the G/C/R-NNN prefix and leading punctuation
+            subj = re.sub(r'^[-*]\s+[GCR]-\d+\s*[—\-]+\s*(?:\[[^\]]+\]\s*)?', '', first_line).strip()
+            fields["subject"] = subj or first_line
+
+        fields["_prefix"] = prefix
+        fields["_num"]    = int(num_str)
+        fields["_block"]  = block
+        findings.append(fields)
+
+    return findings
+
+primary_text   = read_safe(primary_path)
+secondary_text = read_safe(secondary_path)
+
+primary_findings   = extract_findings(primary_text)
+secondary_findings = extract_findings(secondary_text)
+
+# De-duplicate: key by (component, normalised subject). Primary findings win.
+def norm(s):
+    return re.sub(r'\s+', ' ', s.lower().strip())
+
+seen_keys = set()
+merged = []
+for f in primary_findings + secondary_findings:
+    key = (f.get("component", ""), norm(f.get("subject", "")))
+    if key not in seen_keys:
+        seen_keys.add(key)
+        merged.append(f)
+
+# Normalise class values
+CLASS_MAP = {
+    "global-task":           "global-task",
+    "global_task":           "global-task",
+    "global":                "global-task",
+    "per-component-context": "per-component-context",
+    "per_component_context": "per-component-context",
+    "per-component":         "per-component-context",
+    "context":               "per-component-context",
+    "risk":                  "risk",
+}
+
+def normalise_class(raw):
+    return CLASS_MAP.get(raw.lower().replace(" ", "-"), "per-component-context")
+
+for f in merged:
+    f["class"] = normalise_class(f.get("class", ""))
+
+# Sort into buckets and assign sequential numbers
+global_tasks   = [f for f in merged if f["class"] == "global-task"]
+per_comp       = [f for f in merged if f["class"] == "per-component-context"]
+risks          = [f for f in merged if f["class"] == "risk"]
+
+lines = [f"# Cross-cutting findings — {slug}", ""]
+
+lines.append("## Global tasks (need dedicated plan)")
+for i, f in enumerate(global_tasks, 1):
+    gnum    = f"G-{i:03d}"
+    subject = f.get("subject", "(no subject)")
+    comp    = f.get("component", "global")
+    files   = f.get("files", "")
+    entry   = f"- {gnum} — {subject} — component: {comp}"
+    if files:
+        entry += f" — files: {files}"
+    lines.append(entry)
+lines.append("")
+
+lines.append("## Per-component context (inform audits)")
+for i, f in enumerate(per_comp, 1):
+    cnum    = f"C-{i:03d}"
+    comp    = f.get("component", "global")
+    subject = f.get("subject", "(no subject)")
+    lines.append(f"- {cnum} — component: {comp} — {subject}")
+lines.append("")
+
+lines.append("## Risks (watch items)")
+for i, f in enumerate(risks, 1):
+    rnum    = f"R-{i:03d}"
+    comp    = f.get("component", "global")
+    subject = f.get("subject", "(no subject)")
+    lines.append(f"- {rnum} — component: {comp} — {subject}")
+lines.append("")
+
+with open(out_path, "w") as fh:
+    fh.write("\n".join(lines))
+
+print(f"wrote {out_path}: {len(global_tasks)} global-tasks, {len(per_comp)} per-component-context, {len(risks)} risks")
+PYEOF
 ```
 
-Every finding must carry a `component: <slug>` marker. Unclassified findings are placed in the "Per-component context" section.
+Compute `G_COUNT`, `C_COUNT`, and `R_COUNT` immediately after CROSS-CUTTING.md is written — before the Step 6 if-check:
 
+```bash
+G_COUNT="$(python3 -c "
+import re
+with open('$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md') as fh:
+    content = fh.read()
+print(len(re.findall(r'^- G-\d+', content, re.MULTILINE)))
+")"
+C_COUNT="$(python3 -c "
+import re
+with open('$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md') as fh:
+    content = fh.read()
+print(len(re.findall(r'^- C-\d+', content, re.MULTILINE)))
+")"
+R_COUNT="$(python3 -c "
+import re
+with open('$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md') as fh:
+    content = fh.read()
+print(len(re.findall(r'^- R-\d+', content, re.MULTILINE)))
+")"
+```
 ### Step 6 — Create synthetic cross-cutting plan (if global-task count > 0)
 
-Count `G_COUNT` (number of `G-NNN` entries in CROSS-CUTTING.md).
+`G_COUNT` was computed at the end of Step 5. If `G_COUNT > 0`:
 
-If `G_COUNT > 0`:
-
 ```bash
 CROSS_DIR="$(dirname "$Z_HARNESS_PLAN_DIR")/${Z_HARNESS_SLUG}-cross-cutting"
 mkdir -p "$CROSS_DIR"
@@ -931,19 +1114,42 @@
 tasks_lines = []
 if global_section:
     for line in global_section.group(1).splitlines():
-        m = re.match(r'-\s+(G-\d+)\s+[—-]+\s+(?:\[.*?\]\s+)?(.*?)(?:\s+[—-]+\s+files?:\s*(.*))?$', line.strip())
-        if m:
-            gnum    = m.group(1)
-            subject = m.group(2).strip() if m.group(2) else line.strip()
-            files   = m.group(3).strip() if m.group(3) else ""
-            files_line = f"  - {files}" if files else "  - (see CROSS-CUTTING.md)"
-            tasks_lines.append(
-                f"### [{gnum}] {subject}\n"
-                f"- **Files:**\n{files_line}\n"
-                f"- **Depends on:** (none)\n"
-                f"- **Acceptance:** Resolve the cross-cutting issue described in {plan_dir}/CROSS-CUTTING.md#{gnum}.\n"
-            )
+        line = line.strip()
+        if not line.startswith('-'):
+            continue
+        # Parse each finding line-by-line into a field dict, independent of field order
+        fields = {}
+        # Extract the finding number first
+        num_match = re.match(r'-\s+(G-\d+)', line)
+        if not num_match:
+            continue
+        gnum = num_match.group(1)
+        # Parse all key: value pairs by scanning each dash-separated segment
+        for segment in re.split(r'\s+[—\-]+\s+', line):
+            for key in ("component", "files", "subject", "class"):
+                kv = re.match(rf'{re.escape(key)}:\s*(.+)', segment.strip(), re.IGNORECASE)
+                if kv:
+                    fields[key] = kv.group(1).strip()
+        # If subject not found as a key:value, infer from the segment after the gnum
+        if "subject" not in fields:
+            # Remove the leading "- G-NNN" and take the next segment
+            after_num = re.sub(r'^-\s+G-\d+\s*[—\-]*\s*', '', line).strip()
+            # Strip severity tag like [HIGH]
+            after_num = re.sub(r'^\[[^\]]+\]\s*', '', after_num)
+            # Remove any trailing component/files fields
+            after_num = re.split(r'\s+[—\-]+\s+(?:component|files?):', after_num, flags=re.IGNORECASE)[0]
+            fields["subject"] = after_num.strip() or line
 
+        subject    = fields.get("subject", line)
+        files      = fields.get("files", "")
+        files_line = f"  - {files}" if files else "  - (see CROSS-CUTTING.md)"
+        tasks_lines.append(
+            f"### [{gnum}] {subject}\n"
+            f"- **Files:**\n{files_line}\n"
+            f"- **Depends on:** (none)\n"
+            f"- **Acceptance:** Resolve the cross-cutting issue described in {plan_dir}/CROSS-CUTTING.md#{gnum}.\n"
+        )
+
 header = "# Tasks — cross-cutting global tasks\n\nGenerated from CROSS-CUTTING.md global-task findings.\n\n"
 with open(tasks_out, "w") as f:
     f.write(header + "\n".join(tasks_lines) + "\n")
@@ -967,26 +1173,35 @@
 cross_slug = f"{slug}-cross-cutting"
 new_row = f"| [ ] pending | {cross_slug} | (global) | — | — | {cross_dir}/TASKS.md |\n"
 
-# Insert immediately after the header row separator line
-content = re.sub(
-    r'(\|[-| ]+\|\n)',
-    r'\1' + new_row,
-    content,
-    count=1
+# Idempotent: if a row for this cross-slug already exists, update it in place; else insert as first row.
+existing_row_re = re.compile(
+    rf'^\|[^|]*\|\s*{re.escape(cross_slug)}\s*\|[^\n]*\n',
+    re.MULTILINE
 )
+if existing_row_re.search(content):
+    # Update existing row (replace the whole row)
+    content = existing_row_re.sub(new_row, content)
+    print(f"updated existing {cross_slug} row in MANIFEST.md")
+else:
+    # Insert immediately after the header row separator line
+    content = re.sub(
+        r'(\|[-| ]+\|\n)',
+        r'\1' + new_row,
+        content,
+        count=1
+    )
+    print(f"inserted {cross_slug} as first row in MANIFEST.md")
+
 with open(manifest_path, "w") as f:
     f.write(content)
-print(f"inserted {cross_slug} as first row in MANIFEST.md")
 PYEOF
 ```
 
 ### Step 7 — Emit telemetry and checkpoint
 
-```bash
-G_COUNT="$(grep -c '^- G-' "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" 2>/dev/null || echo 0)"
-C_COUNT="$(grep -c '^- C-' "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" 2>/dev/null || echo 0)"
-R_COUNT="$(grep -c '^- R-' "$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md" 2>/dev/null || echo 0)"
+`G_COUNT`, `C_COUNT`, and `R_COUNT` were computed in Step 5 via Python. Reuse those values directly (do not recompute with grep):
 
+```bash
 bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cross_cutting_classified \
   "$(printf '{"slug":"%s","global_tasks":%d,"per_component_context":%d,"risks":%d}' \
      "$SLUG" "$G_COUNT" "$C_COUNT" "$R_COUNT")"
```

Scrutinize this code rigorously for the 8 prior majors and any NEW blockers/majors introduced in v2.

**Scope strictly to the delta above.** Do not re-flag stylistic content. Focus on:
1. Whether M1–M8 were actually fixed
2. Any new blocker/major issues the v2 changes introduced
3. Correctness of the merge logic and field-order independence

Report:
- For each fixed major: confirm it's fixed
- For any unfixed majors: severity blocker, location, fix
- For any new blockers/majors: severity, location, fix
- At end, note any subtle logic bugs in the Python parsing

**OUTPUT BUDGET: strictly under 8000 characters. Blockers and majors only. Confirm fixes first, then report issues.**
