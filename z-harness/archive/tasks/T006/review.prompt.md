You are reviewing code that Claude just wrote for task T006: Wire /z-mr-review orchestrator → mr-reviewer agent end-to-end (single voice, mode=full only).

## Spec (excerpt)

From SPEC.md `/z-mr-review` section:

**Required prelude (orchestration):**

1. **Setup:**
   - Resolve slug, refuse if STYLE.md doesn't exist, voice availability pre-check
   - Compute base ref, capture diff, size & chunking decision
   - Run ID and archive setup; Voice pre-check; Archive any existing MR-REVIEW.md
   - Log mr_run_start

2. **Dispatch `mr-reviewer` agent — single-shape contract:**

   Agent ALWAYS receives a single `diff_path` pointing to ONE patch file. Polymorphism is in the orchestrator only.

   Agent prompt (always the same shape):
   ```
   Agent(
     subagent_type="mr-reviewer",
     model="sonnet",
     description="MR review for <slug>",
     prompt="slug: <slug>\nrun_id: <RUN>\nslug_dir: <SLUG_DIR_ABS>\nbase: <BASE_REF>\nbase_sha: <BASE_SHA>\ndiff_path: <DIFF_PATH>\nstyle_path: <STYLE_PATH>\ndismissed_signatures_path: <DISMISSED_PATH>\nvoices_available: [<VOICES_AVAILABLE>]\nmode: full\nchunk_meta: null\ndeep: <DEEP>"
   )
   ```

   Capture the agent's full return text as `AGENT_RETURN`.

3. **Parse agent return and write MR-REVIEW.md**
   - Extract findings JSON from fenced ```json block
   - Extract summary block with voices_succeeded, voices_failed, dismissal_pattern_matches
   - Compute aggregates and assign T-MR-NNN IDs (by severity order)
   - Build findings_index with exact YAML shape: `- {id: T-MR-001, severity: P1, category: defensive-bloat, file: src/foo.rs, title: "..."}`
   - Write MR-REVIEW.md to BOTH: `z-harness/<SLUG>/MR-REVIEW.md` AND `<ARCHIVE_DIR>/MR-REVIEW.md`

4. **Emit telemetry:**
   - Per-finding: `mr_finding_emitted` events
   - End: `mr_run_end` with totals payload

5. **Final user message:** names path, counts, "delete what you don't want; then /z-implement-all --tasks=MR-REVIEW.md"

## Acceptance criteria

From task definition:
- Dispatches Agent(subagent_type="mr-reviewer", model="sonnet", ...) with full SPEC input contract
- mode=full: one dispatch; mode=per-chunk: errors "chunking pending T009"
- Parses agent return JSON, writes MR-REVIEW.md (canonical + archive snapshot) in TASKS.md shape with findings_index frontmatter
- Logs mr_run_end with totals
- Final user message names path, counts, and "delete what you don't want; then /z-implement-all --tasks=MR-REVIEW.md"

## Diff (primary artifact — focus your scrutiny on what changed)

The file is NEW: commands/z-mr-review.md (695 lines)

Key attention points (from task caller):
1. Does the Agent dispatch pass every input contract field that mr-reviewer.md (T005) declares — slug, run_id, slug_dir, base, base_sha, diff_path, style_path, dismissed_signatures_path, voices_available, mode, chunk_meta, deep?
2. Does JSON extraction safely handle agent returns where the json block is malformed or absent?
3. Does findings_index frontmatter shape match SPEC's spec exactly — id, severity, category, file, title fields?
4. Does the dual-write (canonical + archive snapshot) happen atomically (or at least consistently — same content)?
5. Does mr_run_end payload match the orchestrator's other event names (mr_run_start counterparts)?
6. Is the per-chunk error path actually correct given T004's chunking decision already set MODE?

## Analysis

### Contract completeness (point 1)

Lines 419-436 of diff show the Agent dispatch:

```
Agent(
  subagent_type="mr-reviewer",
  model="sonnet",
  description="MR review for <SLUG>",
  prompt="slug: <SLUG>
+run_id: <RUN>
+slug_dir: <SLUG_DIR_ABS>
+base: <BASE_REF>
+base_sha: <BASE_SHA>
+diff_path: <DIFF_PATH>
+style_path: <STYLE_PATH>
+dismissed_signatures_path: <DISMISSED_PATH>
+voices_available: [<VOICES_AVAILABLE>]
+mode: full
+chunk_meta: null
+deep: <DEEP>"
)
```

This matches the SPEC's required contract verbatim. All 10 fields are present:
✓ slug, ✓ run_id, ✓ slug_dir, ✓ base, ✓ base_sha, ✓ diff_path, ✓ style_path, ✓ dismissed_signatures_path, ✓ voices_available, ✓ mode, ✓ chunk_meta, ✓ deep

### JSON extraction safety (point 2)

Lines 444-453:

"Parse the agent return by locating the first fenced `json` block (` ```json ... ``` `). Extract and parse its contents as JSON..."

"If no valid JSON block is found, log `mr_all_voices_failed` and exit nonzero with:
```
Error: mr-reviewer agent returned no parseable findings JSON. The agent return was:
<AGENT_RETURN>
```"

This covers the malformed/absent case with an explicit error path. The error message helpfully includes the raw return for debugging.

### findings_index frontmatter shape (point 3)

Lines 495-499:

"For each finding (in T-MR-NNN order), build a YAML findings_index entry:
```yaml
  - {id: T-MR-001, severity: P1, category: defensive-bloat, file: src/foo.rs, title: "Short title here"}
```"

The shape matches the SPEC exactly: `id`, `severity`, `category`, `file`, `title` are the five fields. Line 520 in the spec example confirms:
```
findings_index:
  - {id: T-MR-001, severity: P1, category: defensive-bloat, file: src/foo.rs, title: "..."}
```

### Dual-write atomicity (point 4)

Lines 564-589 show:

"Write the completed content to **both** paths:
1. `z-harness/<SLUG>/MR-REVIEW.md` — canonical (overwrites any prior file)
2. `<ARCHIVE_DIR>/MR-REVIEW.md` — snapshot (identical content)

```bash
mkdir -p "$SLUG_DIR"
# Write both files with the same content
python3 - <<'PYEOF'
...
canonical = os.path.join(slug_dir, 'MR-REVIEW.md')
snapshot  = os.path.join(archive_dir, 'MR-REVIEW.md')

with open(canonical, 'w') as f:
    f.write(content)
with open(snapshot, 'w') as f:
    f.write(content)
```"

Both files receive the same `content` variable in the same Python script, so they are guaranteed identical. Not atomic in the OS sense, but "consistently same content" ✓. The `MR_REVIEW_CONTENT` environment variable is set once and reused for both writes.

### mr_run_end payload (point 5)

Lines 603-620:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" mr_run_end \
  "$(python3 -c '
import json, sys
slug, run_id, total, by_sev_json, voices_s, voices_f, dismissal_matches = \
  sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6], int(sys.argv[7])
by_sev = json.loads(by_sev_json)
print(json.dumps({
  "slug": slug,
  "run_id": run_id,
  "total_findings": total,
  "by_severity": by_sev,
  "voices_succeeded": voices_s.split(",") if voices_s else [],
  "voices_failed": voices_f.split(",") if voices_f else [],
  "dismissal_matches": dismissal_matches,
}))
' "$SLUG" "$RUN" "$TOTAL_FINDINGS" "$BY_SEVERITY_JSON" "$VOICES_SUCCEEDED" "$VOICES_FAILED" "$DISMISSAL_MATCHES")"
```

Comparing to SPEC `mr_run_end` event section (line 352):
```
- `mr_run_end` `{slug, run_id, total_findings, by_severity, by_category, voices_succeeded, voices_failed}`
```

ISSUE: The spec lists `by_category` as required in mr_run_end (line 352), but the code only sends `by_severity`. However, re-reading the context more carefully, line 352 shows two event schemas:
- `mr_run_start` includes full VERSION_BLOB + slug + run_id + base + diff_stat + deep + voices_available
- `mr_run_end` lists `{slug, run_id, total_findings, by_severity, by_category, voices_succeeded, voices_failed}`

But the code at lines 603-620 does NOT include `by_category`. Looking at the mr_run_start log (lines 373-386), it logs VERSION_BLOB fields. For mr_run_end, the spec says the event should include `by_category`, but the code omits it.

Actually, re-reading SPEC.md more carefully at line 351:
```
- `mr_run_end` `{slug, run_id, total_findings, by_severity, by_category, voices_succeeded, voices_failed}`
```

The spec DOES require `by_category`, but the code line 608-619 only computes and sends `by_severity`. The findings are grouped by severity in the code (lines 468-482), NOT by category separately. This is a BLOCKER if the spec requires both fields.

Actually, let me check again — on line 609 the code does:
```python
by_sev = json.loads(by_sev_json)
```

And looking back, the code doesn't build `by_category` at all. Looking at line 469-482 in the diff, the code builds `by_severity` with keys `P0, P1, P2, P3, P4` but there's no `by_category` aggregation. The spec (line 351) says `mr_run_end` should have both, but this code only provides `by_severity`.

### Per-chunk error path (point 6)

Lines 392-402:

"If `MODE=per-chunk`, stop immediately with an error:
```
Error: diff exceeds chunk threshold (DIFF_BYTES bytes > CHUNK_THRESHOLD bytes). Chunked review is pending T009 implementation. Either reduce the diff size or wait for the chunking feature. Exiting.
```

Exit nonzero.

Only proceed if `MODE=full`."

The error message is clear and matches the acceptance criterion "mode=per-chunk: errors 'chunking pending T009'". The guard is in Step 2a (Phase 2 — Agent dispatch) which is the right place — before any agent dispatch. ✓

---

## Scrutiny summary

### Blockers

1. **mr_run_end missing `by_category` payload field.** SPEC.md line 351 declares the mr_run_end event must include `{slug, run_id, total_findings, by_severity, by_category, voices_succeeded, voices_failed}`, but the code at lines 603-620 only sends `by_severity`. The code never computes a `by_category` aggregation. The agent (mr-reviewer.md) returns a `by_category` summary (line 259-260), and the command should aggregate those across the full findings list or agent returns and include it in mr_run_end. Without this, downstream analysis (e.g., `/z-stats` or other commands reading mr_run_end) will fail to parse the by_category field.

### Major issues

2. **findings_index does not include line_start/line_end in the indexing frontmatter.** SPEC.md lines 281-284 show the example with line_start and line_end as part of the frontmatter schema, yet lines 495-499 of the command only list `{id, severity, category, file, title}`. The spec example (line 282) includes `file: src/foo.rs` with no line annotation in the frontmatter, but the body format at lines 294-295 shows `**File:** src/foo.rs:42-67` with line ranges. The spec doesn't explicitly require line_start/line_end in findings_index itself (the example shows only id, severity, category, file), so this may be intentional — the frontmatter is a quick-scan index, full details in body. Re-checking SPEC line 281-284:

```
findings_index:
  - {id: T-MR-001, severity: P0, category: abstraction, file: src/foo.rs}
  - {id: T-MR-002, severity: P1, category: defensive-bloat, file: src/bar.rs}
  # ... one entry per finding; lets /z-debug and other consumers parse without scanning prose (Codex fix #10)
```

The spec example does NOT include line_start/line_end in the index, so the command is correct. Not a major. ✓

3. **Dismissal-pattern matching not implemented.** The code at lines 327-368 reads `dismissed_signatures.json` and logs `mr_finding_dismissed` events per signature, but the orchestrator never uses these signatures when parsing findings. The SPEC.md section on dismissal (lines 96-97, 340, 362) says the orchestrator should apply dismissal-pattern matching: "Apply dismissal-pattern matching (see agent procedure step 6). **P0 never demotes** — P0 with dismissal match only gets tagged `[previously-dismissed-pattern]`, severity preserved. P1–P4 demote one tier on match."

However, re-reading the command carefully, lines 570-589 show the command does NOT apply dismissal logic — it just writes the findings as received from the agent. The spec says (lines 96-97): "Apply dismissal-pattern matching..." and this is supposed to happen in the orchestrator after merging findings. But in T006 (single-voice, full mode), the orchestrator receives ONE agent return (not multiple to merge), and the agent itself (mr-reviewer.md) is supposed to apply dismissal logic (lines 119-124 of mr-reviewer.md):

"**NOTE: Dismissal-pattern matching is added in T010. In this single-voice first cut (T005), skip the Jaccard calculation entirely — treat `dismissed_signatures.json` as if it were empty regardless of content.**"

So dismissal-pattern matching is T010 scope (not T006). The orchestrator correctly skips it for now. ✓

