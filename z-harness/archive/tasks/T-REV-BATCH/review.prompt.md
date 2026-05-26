You are reviewing code that Claude just wrote for task T-REV-BATCH: Apply 7 review-task fixes to commands/z-uplift.md.

Spec (excerpt):
The SPEC.md defines several key invariants for z-uplift, including:
- Phase 2 inserts synthetic component `<slug>-cross-cutting` as `[a] audited` (state already processed) so Phase 5 queue includes it immediately
- Phase 3 uses atomic file writes with tmpfile + os.replace to prevent corruption
- Auto-bail check counts CRITICAL+HIGH severity findings structurally, not substring matches
- git grep is guarded to avoid whole-repo scan when OTHER_COMP_PATHS is empty
- Collision resolution loops until collision-free, handles N-way collisions, re-validates custom slugs against regex
- Cross-cutting consultant output is strictly G-NNN/C-NNN/R-NNN formatted; parser warns on drops
- Phase 4 callout when MANIFEST contains -cross-cutting

Acceptance criteria (7 fixes):
T-REV-001: synthetic `-cross-cutting` MANIFEST row inserted as `[a] audited` (not `[ ] pending`), so Phase 5 queue includes it
T-REV-002: Phase 2 Step 6 MANIFEST write uses tmpfile + os.replace (atomic), not direct `open(..., "w")`
T-REV-003: CRIT_HIGH_COUNT counts FINDINGS with CRITICAL/HIGH severity, NOT substring occurrences of those words
T-REV-004: `git grep -- $OTHER_COMP_PATHS` is guarded by `if [ -n "$OTHER_COMP_PATHS" ]` so empty list yields empty DEPS_FOUND (no whole-repo scan)
T-REV-005: collision resolution loops until no duplicates (handles N>2); user-supplied custom slugs are re-validated against to_slug regex AND re-collision-checked before COMPONENTS.md / MANIFEST.md write
T-REV-006: cross-cutting consultant prompt now mandates `G-NNN`/`C-NNN`/`R-NNN` format; parser emits `cross_cutting_findings_dropped` event + warning when bullets don't match
T-REV-007: Phase 4 summary prints a one-line callout when MANIFEST contains a `-cross-cutting` row

Diff (primary artifact):

--- z-harness/plans/tiered-quality-uplift/archive/tasks/T-REV-BATCH/baseline.md	2026-05-26 07:52:32
+++ commands/z-uplift.md	2026-05-26 07:56:13
@@ -872,12 +872,16 @@
 ```
 
 ```bash
-# Apply collision resolution choices (repeat per collision until none remain)
-# User response format: "1", "2", or "<slug-A> <slug-B>"
+# Apply collision resolution choices.
+# Runs in a while-loop until the slug list is collision-free (handles N-way collisions
+# and the case where a user-supplied custom slug introduces a new collision).
+# A safety counter (max 5 passes) prevents infinite loops on pathological input.
 COMPONENTS_JSON="$(python3 - "$COMPONENTS_JSON" "$USER_COLLISION_CHOICES" <<'PYEOF'
-import json, sys
+import json, re, sys
 from collections import defaultdict
 
+SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]*$')
+
 data   = json.loads(sys.argv[1])
 # USER_COLLISION_CHOICES is a JSON array of {"slug": str, "choice": str} objects
 choices = json.loads(sys.argv[2]) if sys.argv[2] else []
@@ -891,22 +895,42 @@
         groups[c["slug"]].append(c)
     return {slug: cs for slug, cs in groups.items() if len(cs) > 1}
 
-collisions = find_collisions(components)
-for slug in sorted(collisions.keys()):
-    colliding = sorted(collisions[slug], key=lambda c: c["path"])
-    choice = choice_map.get(slug, "1")
-    if choice == "1":
-        # A keeps slug; B gets slug-2
-        colliding[1]["slug"] = slug + "-2"
-    elif choice == "2":
-        # B keeps slug; A gets slug-1
-        colliding[0]["slug"] = slug + "-1"
-    else:
-        # Custom: "slug-A slug-B"
-        parts = choice.strip().split()
-        if len(parts) >= 2:
-            colliding[0]["slug"] = parts[0]
-            colliding[1]["slug"] = parts[1]
+MAX_PASSES = 5
+for _pass in range(MAX_PASSES):
+    collisions = find_collisions(components)
+    if not collisions:
+        break
+    for slug in sorted(collisions.keys()):
+        colliding = sorted(collisions[slug], key=lambda c: c["path"])
+        choice = choice_map.get(slug, "1")
+        if choice == "1":
+            # A keeps slug; B gets slug-2
+            colliding[1]["slug"] = slug + "-2"
+        elif choice == "2":
+            # B keeps slug; A gets slug-1
+            colliding[0]["slug"] = slug + "-1"
+        else:
+            # Custom: "slug-A slug-B" — validate each against slug regex before applying
+            parts = choice.strip().split()
+            if len(parts) >= 2:
+                for i, part in enumerate(parts[:2]):
+                    if not SLUG_RE.match(part):
+                        print(f"ERROR: custom slug '{part}' is invalid — must match ^[a-z0-9][a-z0-9-]*$. Aborting.", file=sys.stderr)
+                        sys.exit(1)
+                colliding[0]["slug"] = parts[0]
+                colliding[1]["slug"] = parts[1]
+else:
+    # After MAX_PASSES, check if collisions still remain
+    remaining = find_collisions(components)
+    if remaining:
+        print(f"ERROR: slug collisions remain after {MAX_PASSES} resolution passes: {sorted(remaining.keys())}. Aborting.", file=sys.stderr)
+        sys.exit(1)
+
+# Final re-check: verify no duplicates were introduced by custom choices
+remaining = find_collisions(components)
+if remaining:
+    print(f"ERROR: slug collision introduced by custom choice: {sorted(remaining.keys())}. Re-run with corrected slugs.", file=sys.stderr)
+    sys.exit(1)
 
 data["components"] = components
 print(json.dumps(data))
@@ -1204,7 +1228,9 @@
  - \`risk\` — watch items with no immediately actionable fix
  
  Style-drift findings must cite STYLE rule IDs explicitly.
-Number global-task findings G-001, G-002, ... (include affected files). Number per-component-context findings C-001, C-002, .... Number risk findings R-001, R-002, ...."
+Number global-task findings G-001, G-002, ... (include affected files). Number per-component-context findings C-001, C-002, .... Number risk findings R-001, R-002, ....
+
+CRITICAL FORMAT REQUIREMENT: Each finding MUST be a bullet beginning with \`G-NNN\`, \`C-NNN\`, or \`R-NNN\` (e.g. \`- G-001 ...\`). The orchestrator's parser will silently drop any bullet that does not match this exact pattern."
 ```
 
 ### Step 4 — Dispatch consultants in parallel
@@ -1350,6 +1376,23 @@
  
  for f in merged:
      f["class"] = normalise_class(f.get("class", ""))
+
+# Warn about bullets that looked like findings but were not matched by the strict G/C/R-NNN parser.
+# Counts candidate bullets (any "- <word>" line) across both transcripts, compares against
+# the number actually parsed, and emits a warning + telemetry event if any were dropped.
+combined_text = primary_text + "\n" + secondary_text
+candidate_bullets = re.findall(r'^\s*[-*]\s+\S+', combined_text, re.MULTILINE)
+strict_matched = len(primary_findings) + len(secondary_findings)
+dropped = max(0, len(candidate_bullets) - strict_matched)
+if dropped > 0:
+    import subprocess as _sp, json as _json, os as _os
+    _plugin_root = _os.environ.get("ANTIGRAVITY_PLUGIN_ROOT", _os.environ.get("CLAUDE_PLUGIN_ROOT", ""))
+    _run = _os.environ.get("RUN", "uplift")
+    _sp.run(["bash", _plugin_root + "/scripts/log-event.sh", _run,
+             "cross_cutting_findings_dropped",
+             _json.dumps({"slug": slug, "count": dropped})],
+            check=False)
+    print(f"WARNING: {dropped} bullet(s) in cross-cutting output did not match G-NNN/C-NNN/R-NNN pattern and were dropped.")
 
  # Sort into buckets and assign sequential numbers
  global_tasks   = [f for f in merged if f["class"] == "global-task"]
@@ -1521,7 +1564,8 @@
      content = f.read()
  
  cross_slug = f"{slug}-cross-cutting"
-new_row = f"| [ ] pending | {cross_slug} | (global) | — | — | {cross_dir}/TASKS.md |\n"
+# Inserted as [a] audited so Phase 5 Step 1 queue filter picks it up immediately.
+new_row = f"| [a] audited | {cross_slug} | (global) | — | — | {cross_dir}/TASKS.md |\n"
 
  # Idempotent: if a row for this cross-slug already exists, update it in place; else insert as first row.
  existing_row_re = re.compile(
@@ -1542,8 +1586,12 @@
      )
      print(f"inserted {cross_slug} as first row in MANIFEST.md")
  
-with open(manifest_path, "w") as f:
+# Atomic write: write to a tmp file then os.replace to prevent partial-write corruption.
+import os as _os
+tmp = manifest_path + ".tmp"
+with open(tmp, "w") as f:
      f.write(content)
+_os.replace(tmp, manifest_path)
  PYEOF
  ```
  
@@ -1888,9 +1936,22 @@
  import re, sys
  with open(sys.argv[1]) as f:
      text = f.read()
-# Count lines bearing CRITICAL or HIGH severity tags (case-insensitive)
-count = len(re.findall(r'\b(?:CRITICAL|HIGH)\b', text, re.IGNORECASE))
-print(count)
+# Parse findings structurally: split on finding-start markers, then inspect each block's
+# header for a CRITICAL or HIGH severity tag. This avoids counting prose mentions.
+finding_start_re = re.compile(
+    r'^\s*[-*]\s+(?:F|C|P|D)-\d+|^\s*#{2,4}\s+(?:Finding\s+\d+|F-\d+|C-\d+|P-\d+|D-\d+)',
+    re.MULTILINE
+)
+positions = [m.start() for m in finding_start_re.finditer(text)]
+positions.append(len(text))
+crit_high = 0
+for i in range(len(positions) - 1):
+    block = text[positions[i]:positions[i+1]]
+    head = block[:300]
+    if re.search(r'\bSeverity\s*:?\s*(CRITICAL|HIGH)\b', head, re.IGNORECASE) \
+       or re.match(r'^\s*[-*]\s+(?:F|C|P|D)-\d+\s*\[\s*(?:CRITICAL|HIGH)\s*\]', head, re.IGNORECASE):
+        crit_high += 1
+print(crit_high)
  PYEOF
  )"
  
@@ -1898,9 +1959,12 @@
  import re, sys
  with open(sys.argv[1]) as f:
      text = f.read()
-# Count discrete finding entries: lines starting with a numbered or bullet finding marker
-count = len(re.findall(r'^\s*[-*]\s+(?:F|C|P|D)-\d+|\bFinding\s+\d+\b', text, re.MULTILINE | re.IGNORECASE))
-print(count)
+# Count discrete finding entries by their structural start markers
+finding_start_re = re.compile(
+    r'^\s*[-*]\s+(?:F|C|P|D)-\d+|^\s*#{2,4}\s+(?:Finding\s+\d+|F-\d+|C-\d+|P-\d+|D-\d+)',
+    re.MULTILINE
+)
+print(len(finding_start_re.findall(text)))
  PYEOF
  )"
  ```
@@ -1954,7 +2018,11 @@
  print(' '.join(paths))
  INNEREOF
     )"
-   DEPS_FOUND="$(git grep -l "$COMP_BASENAME" -- $OTHER_COMP_PATHS 2>/dev/null || true)"
+   if [ -n "$OTHER_COMP_PATHS" ]; then
+     DEPS_FOUND="$(git grep -l "$COMP_BASENAME" -- $OTHER_COMP_PATHS 2>/dev/null || true)"
+   else
+     DEPS_FOUND=""
+   fi
     ```
  
  3. Append the dependents section to REPORT.md:
@@ -2320,6 +2388,12 @@
  >
  > Phase 5 will prompt you per-component before dispatching any implementation.
  
+```bash
+if grep -qE '^\| .* \| .*-cross-cutting \|' "$Z_HARNESS_PLAN_DIR/MANIFEST.md"; then
+  echo "Note: '${SLUG}-cross-cutting' will be implemented first (per SPEC §Phase 5)."
+fi
+```
+
  ### Step 3 — Phase telemetry
  
  ```bash

Scrutinize this code rigorously. Claude is prone to over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope beyond the spec.

Report blockers and majors only (skip minors and nits unless they hide a correctness bug). One finding per bullet, two sentences max.

