You are reviewing code that Claude just wrote for task T004: Document SCOPE-*.json schema (extend agents/scope-probe.md).

Spec (excerpt from SPEC.md):

### SCOPE.json Schema Documentation

scope-probe produces a `SCOPE.json` artifact in two forms: a **live file** (namespaced per host command) and an **archive file** (run-scoped). Both use the same schema; the path and naming convention differ.

**File Locations:**
| Form | Path | Notes |
|------|------|-------|
| Live | `z-harness/<slug>/SCOPE-<host>.json` | Namespaced by host command; overwritten on each run. Reader must check `last_run_id` to detect stale entries. |
| Archive | `z-harness/<slug>/archive/<RUN>/SCOPE.json` | Not namespaced — one per run. `host_command` field inside is the discriminator. Never overwritten once written. |

**Write Order Invariant:** Archive-first, then live-overwrite. The archive copy is written (and must succeed) before the live file is updated. If the archive write fails, Phase 0 aborts entirely and the host command proceeds as if scope-probe was never dispatched. This guarantees the live file always has a corresponding archive entry.

**Full Schema Example:**
```json
{
  "host_command":         "z-audit",
  "slug":                 "<target-slug>",
  "last_run_id":          "20260527T175422Z-fanout-escalate-primitive",
  "last_updated":         "2026-05-27T18:00:00Z",
  "mode":                 "HEAVY",
  "axis":                 "per_dimension",
  "confidence":           "high",
  "reason_codes":         ["named_cluster_dir", "module_with_subchildren"],
  "chunks": [
    {"id": "C1", "intent": "...", "scope_hint": "...", "evidence": "..."}
  ],
  "seams_counted": 4,
  "candidates_walked": 2,
  "scope_probe_version": "1"
}
```

**Required 12 fields:** host_command, slug, last_run_id, last_updated, mode, axis, confidence, reason_codes, chunks, seams_counted, candidates_walked, scope_probe_version.

**Optional field:** dimensions_hint (populated by LIGHT in /z-audit; LIGHT mode only).

**Field reference table required** documenting:
- Format
- Writer
- When/how each field is populated
- Constraints

Acceptance criteria:
- Schema documented for both live form (z-harness/<slug>/SCOPE-<host>.json, namespaced) and archive form (z-harness/<slug>/archive/<RUN>/SCOPE.json, run-scoped).
- All 12 required fields documented: host_command, slug, last_run_id, last_updated, mode, axis, confidence, reason_codes, chunks, seams_counted, candidates_walked, scope_probe_version.
- Optional field dimensions_hint documented (populated by LIGHT in /z-audit).
- Archive-first write order invariant documented.

Diff (primary artifact — focus your scrutiny on what changed):

The diff shows agents/scope-probe.md was created as a NEW FILE with 217 lines. The file includes a complete agent specification with:
1. Frontmatter (name, description, tools, model)
2. Mission section
3. Inputs from Caller section
4. 5-step Procedure section
5. Output Contract section
6. Three-State Graceful Degradation section
7. Stable REASON_CODES table
8. Hard Rules section
9. Parser Safety Rule section
10. Error and Edge Case Behavior section
11. **NEW:** SCOPE.json Schema section (lines 148-217)

The SCOPE.json Schema section (lines 148-217) includes:
- File Locations table
- Write Order Invariant subsection
- Full Schema example (JSON)
- Field Reference table (fields, required status, format, writer, notes)
- Archive vs. Live Differences subsection
- Relationship to Other Agents section

Key schema elements documented:
- host_command (string, one of z-audit, z-brainstorm, etc.)
- slug (string, target plan slug)
- last_run_id (string, full run identifier)
- last_updated (ISO 8601 UTC timestamp)
- mode (LIGHT | MEDIUM | HEAVY)
- axis (string from axis_taxonomy | "none")
- confidence (high | medium | low)
- reason_codes (array of strings from stable list)
- chunks (array of chunk objects)
- seams_counted (integer >= 0)
- candidates_walked (integer >= 0)
- scope_probe_version (string, currently "1")
- dimensions_hint (optional, array of strings, LIGHT mode only)

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
