# /z-doc-rationale

You are running **z-harness `/z-doc-rationale`** — the Tier 2 narrative documentation skill. You read incrementally accumulated `tier2-context.json` (3-5K tokens) and produce Architecture Decision Records (ADRs), design rationale, tradeoff explanations, and migration guides.

## Setup

1. **Discover plan slug.** Look for `$Z_HARNESS_PLAN_DIR` or enumerate plans with `tier2-context.json`:
   ```bash
   for d in z-harness/plans/*/; do
     if [ -f "$d/tier2-context.json" ]; then
       echo "$d"
     fi
   done
   ```
   If multiple candidates, ask user to pick. If none, abort: "No tier2-context.json found. Run a full pipeline (z-plan → z-implement-all → z-review-all) first."

2. **Export variables:**
   ```bash
   Z_HARNESS_SLUG=<slug>
   Z_HARNESS_PLAN_DIR=<plan dir>
   ```

3. **Validate tier2-context.json:**
   ```bash
   if ! python3 -c "
   import json, os, sys
   p = os.path.join(os.environ['Z_HARNESS_PLAN_DIR'], 'tier2-context.json')
   d = json.load(open(p))
   if not d.get('finalized'):
       print('NOT_FINALIZED')
       sys.exit(1)
   print('OK')
   "; then
     echo "Error: tier2-context.json is not finalized. Complete the full pipeline first."
     exit 1
   fi
   ```

4. **Memoization check.** Hash tier2-context.json. If `$Z_HARNESS_PLAN_DIR/tier2/.memo` exists and its stored hash matches, skip regeneration:
   ```bash
   CURRENT_HASH="$( (command -v shasum >/dev/null && shasum -a 256 "$Z_HARNESS_PLAN_DIR/tier2-context.json" || sha256sum "$Z_HARNESS_PLAN_DIR/tier2-context.json") | awk '{print $1}')"
   if [ -f "$Z_HARNESS_PLAN_DIR/tier2/.memo" ] && [ "$(cat "$Z_HARNESS_PLAN_DIR/tier2/.memo")" = "$CURRENT_HASH" ]; then
     echo "Tier 2 outputs are up to date (no changes since last run)."
     exit 0
   fi
   ```

## Phase 1 — Generate drafts

Read `tier2-context.json` fully. Spawn a Pro subagent to produce drafts:

```
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
  subagent_type="doc-updater",
  model="sonnet",
  description="Tier 2 narrative doc generation for <slug>",
  prompt="Generate narrative documentation from this Tier 2 context:

<tier2-context.json contents>

Produce the following documents:

### 1. Architecture Decision Records (ADRs)
For each decision in decisions[] where adr_worthy: true:
- ADR-NNN-<title>.md following the standard ADR format:
  - Title, Status (accepted), Context, Decision, Consequences
  - Include consultant_consensus and human_override if present
  - Include the rationale from the decision

### 2. Design Rationale (rationale.md)
A narrative document covering:
- Summary (from spec_summary, plan_summary)
- Key decisions and why each was made
- Tradeoffs considered and rejected
- Patterns that emerged across tasks (from review_patterns[])
- Cross-LLM consultation findings (from consultant_findings[])

### 3. Migration Guide (migration-guide.md)
Only if breaking_changes[] or deviations[] are non-empty:
- Breaking API changes (from breaking_changes[]: old → new, consumers affected)
- Plan deviations (from deviations[]: what differed from plan and why)
- Upgrade steps for consumers

### 4. Tried and Failed
Include a section in rationale.md:
> ⚠ Auto-generated from implementer self-reports. May contain inferred
> or incomplete information. Reviewer validation: partial.

For each entry in tried_and_failed[]:
- Task, concept, what was tried, why it failed, what was chosen
- Source attribution: 'Source: <task> implementer TRIED. Reviewer did not validate.'"
)
```

Save draft outputs to `$Z_HARNESS_PLAN_DIR/tier2/drafts/`.

## Phase 2 — Gap-fill conversation

Read `tier2-context.json.gaps[]`. For each gap with `status: missing`:

```
Gap: <gap.field>
Note: <gap.note>

Type the missing information or press Enter to skip:
```

- If user provides text → fill the gap in the relevant output document
- If user presses Enter → leave gap flagged; document ships with honest gap annotation: "> ⚠ Reason not captured at decision time."

**Present only gaps, not the full document review.** The user should spend ≤30 seconds on this phase.

## Phase 3 — Write finals

1. **ADRs:** Write to `$Z_HARNESS_PLAN_DIR/tier2/ADR-NNN-<title>.md`
   - ADR numbering: read `docs/adr/` if it exists; find max N; allocate N+1, N+2, etc.
   - If no `docs/adr/` exists, start at ADR-001

2. **Rationale:** Write to `$Z_HARNESS_PLAN_DIR/tier2/rationale.md`

3. **Migration guide:** Write to `$Z_HARNESS_PLAN_DIR/tier2/migration-guide.md` (only if content exists)

4. **Cross-link into concept docs:**
   For each concept touched by this plan's decisions, append a `design-decisions` section to its human doc:
   ```markdown
   <!-- AUTO-START: design-decisions -->
   ## Design decisions
   - [ADR-NNN: <title>](../tier2/ADR-NNN-<title>.md)
   <!-- AUTO-END: design-decisions -->
   ```
   If the section already exists (AUTO markers present), update it. If not, append at end of doc.

5. **Memoize:**
   ```bash
   mkdir -p "$Z_HARNESS_PLAN_DIR/tier2"
   ( (command -v shasum >/dev/null && shasum -a 256 "$Z_HARNESS_PLAN_DIR/tier2-context.json" || sha256sum "$Z_HARNESS_PLAN_DIR/tier2-context.json") | awk '{print $1}' ) > "$Z_HARNESS_PLAN_DIR/tier2/.memo"
   ```

## Phase 4 — Finalize

Report:
```
/z-doc-rationale complete.
  ADRs: <N>
  Rationale: rationale.md
  Migration guide: <migration-guide.md or "not needed">
  Gaps filled: <M>/<total>
```

**Push notification:** "Tier 2 docs ready: <N> ADRs, rationale, <migration status>."

Recommended next:
```
/z-review-all    — (if not yet run) final-gate cross-LLM review
/z-implement-all — (if review findings need implementation)
```

## Confidence caveat

All tried-and-failed entries include source attribution and the following banner:

> ⚠ Auto-generated from implementer self-reports during pipeline execution.
> May contain inferred or incomplete information. Reviewer validation: partial.
> Entries marked "Reviewer did not validate" were self-reported by the implementing
> agent and were not independently verified.

Documents ship with honest gaps — never fabricate content for missing human override reasons.

## Invariants

- Never fabricate gap content
- Preserve human_overrides[] with captured-at-decision-time reasons
- Skip regeneration if tier2-context.json unchanged (memoization)
- Honest gaps: "Reason not captured at decision time" for missing human overrides
